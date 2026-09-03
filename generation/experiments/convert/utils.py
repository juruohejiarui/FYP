#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Shared utilities for the multi-stage conversion pipeline."""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from tqdm import tqdm
from loguru import logger
from openai import AsyncOpenAI


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class EmptyResponseError(Exception):
    """Raised when LLM returns empty content (DeepSeek thinking bug)."""


class TokenTruncationError(Exception):
    """Raised when response truncated - thinking consumed all max_tokens."""


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------


def extract_json_object(text: str) -> Dict[str, Any]:
    """Robust JSON extraction from LLM output."""
    text = text.strip()
    if not text:
        raise ValueError(
            "Empty model output (known DeepSeek thinking bug: "
            "content may be empty while reasoning_content has data)"
        )

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

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
                start = -1

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
    """Load a prompt and strip top-level markdown headers."""
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
    """Call fn(*args, **kwargs) with exponential backoff on exception."""
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            tag = f" [{label}]" if label else ""
            logger.warning(f"Attempt {attempt}/{max_retries}{tag} failed: {exc}")
            if attempt < max_retries:
                delay = base_delay * (2 ** (attempt - 1))
                time.sleep(delay)
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
    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_completion_tokens" if provider == "doubao" else "max_tokens": 
            max_tokens
    }

    if provider in ["deepseek", "doubao"] :
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
                completion_tokens = getattr(usage, "completion_tokens", "?") if usage else "?"
                raise TokenTruncationError(
                    f"Response truncated at {max_tokens} max_tokens "
                    f"(completion_tokens={completion_tokens})."
                )
            if thinking_enabled:
                reasoning = getattr(resp.choices[0].message, "reasoning_content", None) or ""
                if reasoning.strip():
                    logger.warning("DeepSeek empty content - using reasoning_content")
                    return reasoning
            raise EmptyResponseError(f"Empty content (finish_reason={finish_reason})")
        return content

    elif provider in ["qwen"] :
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

        kwargs["temperature"] = temperature
        kwargs["extra_body"] = {"enable_thinking": False}
        kwargs["response_format"] = {"type": "json_object"}

        resp = await client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

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
                f"truncated at {current_max_tokens} - retrying with {new_limit}"
            )
            current_max_tokens = new_limit
            continue
        except EmptyResponseError:
            if use_thinking:
                logger.warning(
                    f"Attempt {attempt}/{max_retries} [{stage_label}] "
                    "empty - retrying without thinking"
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


async def async_stage_llm_call(
    stage_name: str,
    user_content: str,
    *,
    system_prompt: str,
    config: Any,
    client: AsyncOpenAI,
) -> Dict[str, Any]:
    """Stage-aware async LLM call using PipelineConfig's stage/model settings."""
    stage_cfg = config.get_stage_config(stage_name)
    model = config.get_model_for_stage(stage_name)

    messages: List[Dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_content})

    # tqdm.write(
    #     f"[{stage_cfg.label}] model={model} effort={stage_cfg.thinking_effort} "
    #     f"temp={stage_cfg.temperature}"
    # )

    return await async_call_llm_structured(
        messages=messages,
        client=client,
        model=model,
        max_tokens=stage_cfg.max_tokens,
        temperature=stage_cfg.temperature,
        thinking_enabled=config.thinking_enabled,
        thinking_effort=stage_cfg.thinking_effort,
        provider=config.provider,
        max_retries=config.max_retries,
        stage_label=stage_cfg.label,
    )


def save_intermediates(
    dialogue_id: Any,
    intermediates: Dict[str, Any],
    intermediates_dir: Optional[Path],
) -> None:
    """Save intermediate stage outputs to disk for inspection."""
    if not intermediates_dir:
        return

    out_dir = intermediates_dir / str(dialogue_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    for key, value in intermediates.items():
        path = out_dir / f"{key}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
    tqdm.write(f"Intermediates saved to {out_dir}")


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------


def safe_name(text: str) -> str:
    """Sanitize a string for use as a filename component."""
    text = re.sub(r"[^\w一-鿿\-]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_").strip("_")
    return text[:80] if text else "sample"
