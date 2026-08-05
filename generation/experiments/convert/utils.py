#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Shared utilities for the multi-stage conversion pipeline."""

from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import asyncio

from loguru import logger
from openai import AsyncOpenAI, OpenAI


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class EmptyResponseError(Exception):
    """Raised when LLM returns empty content (DeepSeek thinking bug)."""
    pass


class TokenTruncationError(Exception):
    """Raised when response truncated — thinking consumed all max_tokens."""
    pass


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

def extract_json_object(text: str) -> Dict[str, Any]:
    """Robust JSON extraction from LLM output.

    Handles: ```json fences, stray markdown, and models that wrap JSON in prose.
    Falls back to regex extraction if direct parse fails.
    """
    text = text.strip()
    if not text:
        raise ValueError(
            "Empty model output (known DeepSeek thinking bug: "
            "content may be empty while reasoning_content has data)"
        )

    # Strip ```json / ``` fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

    # Fast path: direct parse
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # Fallback: find the first balanced JSON object
    # Try finding outermost { ... }
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                candidate = text[start : i + 1]
                try:
                    obj = json.loads(candidate)
                    if isinstance(obj, dict):
                        return obj
                except Exception:
                    pass
                # Continue searching for later objects
                start = -1

    # Last resort: regex search for any { ... }
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("No JSON object found in model output")
    obj = json.loads(m.group(0))
    if not isinstance(obj, dict):
        raise ValueError("Model output is not a JSON object")
    return obj


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(name: str) -> str:
    """Load a prompt markdown file by name (without .md extension)."""
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def load_prompt_stripped(name: str) -> str:
    """Load a prompt and strip top-level markdown headers (lines starting with '# ')."""
    content = load_prompt(name)
    lines = content.splitlines()
    cleaned = []
    for line in lines:
        if line.strip().startswith("# ") and not line.strip().startswith("## "):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


# ---------------------------------------------------------------------------
# Retry wrapper
# ---------------------------------------------------------------------------

def retry_with_backoff(
    fn,
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    label: str = "",
    **kwargs,
) -> Any:
    """Call `fn(*args, **kwargs)` with exponential backoff on exception.

    Returns the function's return value on first success.
    Raises the last exception after exhausting retries.
    """
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            tag = f" [{label}]" if label else ""
            logger.warning(
                f"Attempt {attempt}/{max_retries}{tag} failed: {exc}"
            )
            if attempt < max_retries:
                delay = base_delay * (2 ** (attempt - 1))
                time.sleep(delay)
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Unified LLM call
# ---------------------------------------------------------------------------

def call_llm(
    messages: List[Dict[str, str]],
    *,
    client: OpenAI,
    model: str,
    max_tokens: int = 4096,
    temperature: float = 0.4,
    thinking_enabled: bool = True,
    thinking_effort: Optional[str] = None,
    provider: str = "deepseek",
    **_kwargs,
) -> str:
    """Call an LLM with provider-specific thinking and structured-output config.

    Parameters
    ----------
    messages : list of {"role": ..., "content": ...}
    client : OpenAI client instance
    model : model name string
    max_tokens : max completion tokens (default 4096)
    temperature : sampling temperature
    thinking_enabled : whether to enable thinking/reasoning mode
    thinking_effort : reasoning effort level (provider-specific). For DeepSeek:
        "low"/"high"/"max". For Qwen: ignored for most models; "low".."max"
        for qwen3.8-max.
    provider : "deepseek" or "qwen"

    Returns
    -------
    The model's text response (content string).
    """
    kwargs: Dict[str, Any] = dict(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
    )

    if provider == "deepseek":
        kwargs["temperature"] = temperature
        if thinking_enabled:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
            if thinking_effort:
                kwargs["reasoning_effort"] = thinking_effort
            # response_format works fine with DeepSeek thinking
            kwargs["response_format"] = {"type": "json_object"}
        else:
            kwargs["response_format"] = {"type": "json_object"}

        resp = client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content or ""
        finish_reason = getattr(resp.choices[0], "finish_reason", None)

        if not content.strip():
            # Mode A: thinking consumed all max_tokens → truncated
            if finish_reason == "length":
                usage = getattr(resp, "usage", None)
                completion_tokens = getattr(usage, "completion_tokens", "?") if usage else "?"
                raise TokenTruncationError(
                    f"Response truncated at {max_tokens} max_tokens "
                    f"(completion_tokens={completion_tokens}). "
                    f"Thinking likely consumed all tokens. "
                    f"Retry with higher max_tokens."
                )

            # Mode B: JSON landed in reasoning_content instead of content
            if thinking_enabled:
                reasoning = getattr(
                    resp.choices[0].message, "reasoning_content", None
                ) or ""
                if reasoning.strip():
                    logger.warning(
                        "DeepSeek returned empty content — "
                        "falling back to reasoning_content"
                    )
                    content = reasoning
                    return content

            # Mode C: genuinely empty
            raise EmptyResponseError(
                f"DeepSeek returned empty content "
                f"(finish_reason={finish_reason}). "
                f"Will retry without thinking."
            )

        return content

    elif provider == "qwen":
        if thinking_enabled:
            # Qwen thinking requires streaming + no response_format + temp>=1.0
            kwargs["stream"] = True
            kwargs["temperature"] = max(temperature, 1.0)
            kwargs["extra_body"] = {"enable_thinking": True}
            if thinking_effort:
                kwargs["reasoning_effort"] = thinking_effort

            chunks = []
            for chunk in client.chat.completions.create(**kwargs):
                if chunk.choices and chunk.choices[0].delta.content:
                    chunks.append(chunk.choices[0].delta.content)
            return "".join(chunks)
        else:
            kwargs["temperature"] = temperature
            kwargs["extra_body"] = {"enable_thinking": False}
            kwargs["response_format"] = {"type": "json_object"}

            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""

    else:
        raise ValueError(f"Unknown provider: {provider}")


def call_llm_structured(
    messages: List[Dict[str, str]],
    *,
    client: OpenAI,
    model: str,
    max_tokens: int = 4096,
    temperature: float = 0.4,
    thinking_enabled: bool = True,
    thinking_effort: Optional[str] = None,
    provider: str = "deepseek",
    max_retries: int = 3,
    stage_label: str = "",
) -> Dict[str, Any]:
    """Call LLM and parse response as JSON, with retries.

    Wraps call_llm() + extract_json_object() + retry_with_backoff().
    On EmptyResponseError (DeepSeek thinking bug), retries without thinking.
    """
    last_exc = None
    use_thinking = thinking_enabled
    current_max_tokens = max_tokens

    for attempt in range(1, max_retries + 1):
        try:
            raw = call_llm(
                messages=messages,
                client=client,
                model=model,
                max_tokens=current_max_tokens,
                temperature=temperature,
                thinking_enabled=use_thinking,
                thinking_effort=thinking_effort if use_thinking else None,
                provider=provider,
            )
            return extract_json_object(raw)
        except TokenTruncationError:
            new_limit = current_max_tokens * 2
            logger.warning(
                f"Attempt {attempt}/{max_retries} [{stage_label}] "
                f"truncated at {current_max_tokens} tokens — "
                f"retrying with {new_limit}"
            )
            current_max_tokens = new_limit
            continue
        except EmptyResponseError:
            if use_thinking:
                logger.warning(
                    f"Attempt {attempt}/{max_retries} [{stage_label}] "
                    f"empty response — retrying with thinking disabled"
                )
                use_thinking = False
                continue
            last_exc = EmptyResponseError(
                "Empty response persists even without thinking"
            )
            logger.warning(
                f"Attempt {attempt}/{max_retries} [{stage_label}] failed: {last_exc}"
            )
        except Exception as exc:
            last_exc = exc
            logger.warning(
                f"Attempt {attempt}/{max_retries} [{stage_label}] failed: {exc}"
            )
            if attempt < max_retries:
                time.sleep(2 ** (attempt - 1))

    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Async LLM call
# ---------------------------------------------------------------------------

async def async_call_llm(
    messages: List[Dict[str, str]],
    *,
    client: AsyncOpenAI,
    model: str,
    max_tokens: int = 4096,
    temperature: float = 0.4,
    thinking_enabled: bool = True,
    thinking_effort: Optional[str] = None,
    provider: str = "deepseek",
    **_kwargs,
) -> str:
    """Async version of call_llm()."""
    kwargs: Dict[str, Any] = dict(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
    )

    if provider == "deepseek":
        kwargs["temperature"] = temperature
        if thinking_enabled:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
            if thinking_effort:
                kwargs["reasoning_effort"] = thinking_effort
            kwargs["response_format"] = {"type": "json_object"}
        else:
            kwargs["response_format"] = {"type": "json_object"}

        resp = await client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content or ""
        finish_reason = getattr(resp.choices[0], "finish_reason", None)

        if not content.strip():
            if finish_reason == "length":
                usage = getattr(resp, "usage", None)
                ct = getattr(usage, "completion_tokens", "?") if usage else "?"
                raise TokenTruncationError(
                    f"Response truncated at {max_tokens} (completion_tokens={ct})"
                )
            if thinking_enabled:
                reasoning = getattr(resp.choices[0].message, "reasoning_content", None) or ""
                if reasoning.strip():
                    logger.warning("DeepSeek empty content — using reasoning_content")
                    content = reasoning
                    return content
            raise EmptyResponseError(
                f"Empty content (finish_reason={finish_reason})"
            )
        return content

    elif provider == "qwen":
        if thinking_enabled:
            kwargs["stream"] = True
            kwargs["temperature"] = max(temperature, 1.0)
            kwargs["extra_body"] = {"enable_thinking": True}
            if thinking_effort:
                kwargs["reasoning_effort"] = thinking_effort

            chunks = []
            async for chunk in await client.chat.completions.create(**kwargs):
                if chunk.choices and chunk.choices[0].delta.content:
                    chunks.append(chunk.choices[0].delta.content)
            return "".join(chunks)
        else:
            kwargs["temperature"] = temperature
            kwargs["extra_body"] = {"enable_thinking": False}
            kwargs["response_format"] = {"type": "json_object"}

            resp = await client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""

    else:
        raise ValueError(f"Unknown provider: {provider}")


async def async_call_llm_structured(
    messages: List[Dict[str, str]],
    *,
    client: AsyncOpenAI,
    model: str,
    max_tokens: int = 4096,
    temperature: float = 0.4,
    thinking_enabled: bool = True,
    thinking_effort: Optional[str] = None,
    provider: str = "deepseek",
    max_retries: int = 3,
    stage_label: str = "",
) -> Dict[str, Any]:
    """Async version of call_llm_structured()."""
    last_exc = None
    use_thinking = thinking_enabled
    current_max_tokens = max_tokens

    for attempt in range(1, max_retries + 1):
        try:
            raw = await async_call_llm(
                messages=messages,
                client=client,
                model=model,
                max_tokens=current_max_tokens,
                temperature=temperature,
                thinking_enabled=use_thinking,
                thinking_effort=thinking_effort if use_thinking else None,
                provider=provider,
            )
            return extract_json_object(raw)
        except TokenTruncationError:
            new_limit = current_max_tokens * 2
            logger.warning(
                f"Attempt {attempt}/{max_retries} [{stage_label}] "
                f"truncated at {current_max_tokens} — retrying with {new_limit}"
            )
            current_max_tokens = new_limit
            continue
        except EmptyResponseError:
            if use_thinking:
                logger.warning(
                    f"Attempt {attempt}/{max_retries} [{stage_label}] "
                    f"empty — retrying without thinking"
                )
                use_thinking = False
                continue
            last_exc = EmptyResponseError("Empty even without thinking")
            logger.warning(f"Attempt {attempt}/{max_retries} [{stage_label}] failed: {last_exc}")
        except Exception as exc:
            last_exc = exc
            logger.warning(f"Attempt {attempt}/{max_retries} [{stage_label}] failed: {exc}")
            if attempt < max_retries:
                await asyncio.sleep(2 ** (attempt - 1))

    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

def safe_name(text: str) -> str:
    """Sanitize a string for use as a filename component."""
    text = re.sub(r"[^\w一-鿿\-]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:80] if text else "sample"


def _resolve_audio_entry(entry: Any) -> Optional[Dict[str, str]]:
    """Resolve an audio config entry to {"wav": ..., "prompt_text": ...}.

    Handles both old format (plain string path) and new format (dict with wav + prompt_text).
    """
    if entry is None:
        return None
    if isinstance(entry, str):
        return {"wav": entry, "prompt_text": ""}
    if isinstance(entry, dict):
        return {
            "wav": str(entry.get("wav", "")),
            "prompt_text": str(entry.get("prompt_text", "")),
        }
    return None


def select_audio_refs(
    sex: Optional[str],
    audio_map: Dict[str, Any],
) -> Dict[str, Optional[Dict[str, str]]]:
    """Select patient and doctor reference audio paths + prompt texts based on patient sex.

    Parameters
    ----------
    sex : "男", "女", or None
    audio_map : parsed convert.json dict with "male", "female", "default" keys.
        Each role entry can be a string (wav path), a dict {"wav": ..., "prompt_text": ...},
        or a list of either.

    Returns
    -------
    {
        "patient_ref": {"wav": path, "prompt_text": text} or None,
        "doctor_ref": {"wav": path, "prompt_text": text} or None,
    }
    """
    gender_key = None
    if sex == "男":
        gender_key = "male"
    elif sex == "女":
        gender_key = "female"

    def _pick(role: str) -> Optional[Dict[str, str]]:
        # Try gender-specific first
        if gender_key and gender_key in audio_map:
            entry = audio_map[gender_key].get(role)
            if isinstance(entry, list) and entry:
                return _resolve_audio_entry(random.choice(entry))
            resolved = _resolve_audio_entry(entry)
            if resolved and resolved["wav"]:
                return resolved
        # Fallback to default
        default = audio_map.get("default", {})
        entry = default.get(role)
        if isinstance(entry, list) and entry:
            return _resolve_audio_entry(random.choice(entry))
        resolved = _resolve_audio_entry(entry)
        if resolved and resolved["wav"]:
            return resolved
        return None

    return {
        "patient_ref": _pick("patient"),
        "doctor_ref": _pick("doctor"),
    }
