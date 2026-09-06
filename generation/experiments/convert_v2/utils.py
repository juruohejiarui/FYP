#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Provider-neutral LLM calls for convert_v2.

JSON stages are parsed into objects. Line-plan stages keep the raw model text
and pass it downstream unchanged.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from loguru import logger
from tqdm import tqdm

from .config import resolve_gemini_thinking


class EmptyResponseError(RuntimeError):
    """Raised when a provider returns no usable generated text."""


class TokenTruncationError(RuntimeError):
    """Raised when a provider reports that generation ended because of length."""


def extract_json_object(text: str) -> Dict[str, Any]:
    """Extract one JSON object from plain text or a Markdown code fence."""
    text = text.strip()
    if not text:
        raise EmptyResponseError("Model returned an empty response")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    depth = 0
    start = -1
    for index, character in enumerate(text):
        if character == "{":
            if depth == 0:
                start = index
            depth += 1
        elif character == "}" and depth:
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    value = json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    start = -1
                    continue
                if isinstance(value, dict):
                    return value
                start = -1
    raise ValueError("No JSON object found in model output")


def normalize_stage_text(text: str) -> str:
    """Strip fences around a line-plan block, otherwise keep the model text."""
    text = text.strip()
    if not text:
        raise EmptyResponseError("Model returned an empty response")
    if text.startswith("```"):
        text = re.sub(r"^```(?:text|markdown|md)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
        if not text:
            raise EmptyResponseError("Model returned an empty fenced response")
    return text


async def _call_gemini(
    messages: List[Dict[str, str]],
    *,
    client: Any,
    model: str,
    max_tokens: int,
    temperature: float,
    thinking_enabled: bool,
    thinking_effort: Optional[str],
    output_kind: str,
) -> str:
    try:
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "Gemini support requires google-genai. Install it with: pip install -U google-genai"
        ) from exc

    system_parts = [item["content"] for item in messages if item["role"] == "system"]
    user_parts = [item["content"] for item in messages if item["role"] != "system"]
    thinking_settings = resolve_gemini_thinking(
        model,
        thinking_enabled,
        thinking_effort,
    )
    config_kwargs: Dict[str, Any] = {
        "system_instruction": "\n\n".join(system_parts) or None,
        "temperature": temperature,
        "max_output_tokens": max_tokens,
        "thinking_config": types.ThinkingConfig(**thinking_settings),
    }
    if output_kind == "json":
        config_kwargs["response_mime_type"] = "application/json"
    config = types.GenerateContentConfig(**config_kwargs)
    response = await client.aio.models.generate_content(
        model=model,
        contents="\n\n".join(user_parts),
        config=config,
    )
    try:
        text = response.text or ""
    except (AttributeError, ValueError):
        text = ""
    if not text.strip():
        raise EmptyResponseError("Gemini returned no textual response")
    return text


async def async_call_llm(
    messages: List[Dict[str, str]],
    *,
    client: Any,
    model: str,
    max_tokens: int,
    temperature: float,
    thinking_enabled: bool,
    thinking_effort: Optional[str],
    provider: str,
    output_kind: str,
) -> str:
    """Generate one response through the configured provider."""
    if provider == "gemini":
        return await _call_gemini(
            messages,
            client=client,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            thinking_enabled=thinking_enabled,
            thinking_effort=thinking_effort,
            output_kind=output_kind,
        )

    request: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if provider == "deepseek":
        if output_kind == "json":
            request["response_format"] = {"type": "json_object"}
        if thinking_enabled:
            request["extra_body"] = {"thinking": {"type": "enabled"}}
            if thinking_effort:
                request["reasoning_effort"] = thinking_effort
        response = await client.chat.completions.create(**request)
        choice = response.choices[0]
        content = choice.message.content or ""
        if content.strip():
            return content
        if getattr(choice, "finish_reason", None) == "length":
            raise TokenTruncationError(f"DeepSeek stopped at {max_tokens} tokens")
        reasoning = getattr(choice.message, "reasoning_content", None) or ""
        if thinking_enabled and reasoning.strip():
            logger.warning("DeepSeek returned reasoning text instead of final content")
            return reasoning
        raise EmptyResponseError("DeepSeek returned empty content")

    if provider == "qwen":
        request["extra_body"] = {"enable_thinking": bool(thinking_enabled)}
        if thinking_enabled:
            request["stream"] = True
            request["temperature"] = max(temperature, 1.0)
            if thinking_effort:
                request["reasoning_effort"] = thinking_effort
            chunks: List[str] = []
            stream = await client.chat.completions.create(**request)
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    chunks.append(chunk.choices[0].delta.content)
            content = "".join(chunks)
        else:
            if output_kind == "json":
                request["response_format"] = {"type": "json_object"}
            response = await client.chat.completions.create(**request)
            content = response.choices[0].message.content or ""
        if not content.strip():
            raise EmptyResponseError("Qwen returned empty content")
        return content

    raise ValueError(f"Unsupported provider: {provider}")


async def async_call_llm_raw(
    messages: List[Dict[str, str]],
    *,
    client: Any,
    model: str,
    max_tokens: int,
    temperature: float,
    thinking_enabled: bool,
    thinking_effort: Optional[str],
    provider: str,
    max_retries: int,
    stage_label: str,
    output_kind: str,
) -> str:
    """Call a model with retries and return the raw generated text."""
    last_error: Optional[Exception] = None
    use_thinking = thinking_enabled
    token_limit = max_tokens
    for attempt in range(1, max_retries + 1):
        try:
            return await async_call_llm(
                messages,
                client=client,
                model=model,
                max_tokens=token_limit,
                temperature=temperature,
                thinking_enabled=use_thinking,
                thinking_effort=thinking_effort if use_thinking else None,
                provider=provider,
                output_kind=output_kind,
            )
        except TokenTruncationError as exc:
            last_error = exc
            token_limit *= 2
            logger.warning(
                f"[{stage_label}] attempt {attempt}/{max_retries} truncated; retrying with {token_limit} tokens"
            )
        except EmptyResponseError as exc:
            last_error = exc
            if use_thinking and provider != "gemini":
                use_thinking = False
                logger.warning(
                    f"[{stage_label}] empty response; retrying once without thinking"
                )
            else:
                logger.warning(f"[{stage_label}] attempt {attempt}/{max_retries}: {exc}")
        except Exception as exc:
            last_error = exc
            logger.warning(f"[{stage_label}] attempt {attempt}/{max_retries}: {exc}")
        if attempt < max_retries:
            await asyncio.sleep(2 ** (attempt - 1))
    raise last_error or RuntimeError(f"[{stage_label}] failed without an error")


async def async_stage_llm_call(
    stage_name: str,
    user_content: str,
    *,
    system_prompt: str,
    config: Any,
    client: Any,
) -> Union[str, Dict[str, Any]]:
    """Execute a named stage. JSON stages return a dict; line-plan stages return text."""
    stage_config = config.get_stage_config(stage_name)
    model = config.get_model_for_stage(stage_name)
    output_kind = config.output_kind(stage_name)
    thinking_suffix = ""
    if config.provider == "gemini":
        settings = config.get_gemini_thinking(stage_name)
        thinking_suffix = f" gemini_thinking={settings}"
    tqdm.write(
        f"[{stage_config.label}] model={model} effort={stage_config.thinking_effort} "
        f"temp={stage_config.temperature} kind={output_kind}{thinking_suffix}"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    raw = await async_call_llm_raw(
        messages,
        client=client,
        model=model,
        max_tokens=stage_config.max_tokens,
        temperature=stage_config.temperature,
        thinking_enabled=config.thinking_enabled,
        thinking_effort=stage_config.thinking_effort,
        provider=config.provider,
        max_retries=config.max_retries,
        stage_label=stage_config.label,
        output_kind=output_kind,
    )
    if output_kind == "json":
        return extract_json_object(raw)
    return normalize_stage_text(raw)


def save_intermediates(
    dialogue_id: Any,
    intermediates: Dict[str, Any],
    intermediates_dir: Optional[Path],
) -> None:
    """Save traceable stage outputs when --save-intermediates is enabled."""
    if not intermediates_dir:
        return
    destination = intermediates_dir / str(dialogue_id)
    destination.mkdir(parents=True, exist_ok=True)
    for name, value in intermediates.items():
        if isinstance(value, str):
            (destination / f"{name}.txt").write_text(value, encoding="utf-8")
        else:
            (destination / f"{name}.json").write_text(
                json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    tqdm.write(f"Intermediates saved to {destination}")
