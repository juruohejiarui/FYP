#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Per-stage LLM settings for convert_v3.

JSON files supply a default block plus optional per-stage overlays.
Clients are cached by provider, API key, and base URL.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from openai import AsyncOpenAI


THIS_DIR = Path(__file__).resolve().parent
ENV_FILE = THIS_DIR / ".env"

KNOWN_STAGES = (
    "stage0_meta_inference",
    "stage1_clinical_brief",
    "stage1_clinical_brief_repair",
    "stage2_encounter_director",
    "stage2_encounter_director_repair",
    "stage3_spoken_performance_plan",
    "stage3_spoken_performance_plan_repair",
    "stage4_spoken_base",
    "stage4_spoken_base_repair",
    "stage5_disfluency_plan",
    "stage6_surface_generation",
    "stage6_surface_repair",
    "stage7_clinical_naturalness_judge",
)

STAGE_LABELS = {
    "stage0_meta_inference": "Meta Inference",
    "stage1_clinical_brief": "Clinical Brief",
    "stage1_clinical_brief_repair": "Clinical Brief Repair",
    "stage2_encounter_director": "Encounter Director",
    "stage2_encounter_director_repair": "Encounter Director Repair",
    "stage3_spoken_performance_plan": "Spoken Performance Plan",
    "stage3_spoken_performance_plan_repair": "Spoken Performance Plan Repair",
    "stage4_spoken_base": "Spoken Base",
    "stage4_spoken_base_repair": "Spoken Base Repair",
    "stage5_disfluency_plan": "Disfluency Plan",
    "stage6_surface_generation": "Surface Generation",
    "stage6_surface_repair": "Surface Repair",
    "stage7_clinical_naturalness_judge": "Clinical/Naturalness Judge",
}

JSON_STAGES = {
    "stage0_meta_inference",
    "stage6_surface_generation",
    "stage6_surface_repair",
    "stage7_clinical_naturalness_judge",
}

LLM_FIELDS = (
    "provider",
    "api_key",
    "llm",
    "max_token",
    "reason_effort",
    "temperature",
    "base_url",
)


def load_dotenv() -> None:
    """Load the first available project .env without an extra dependency."""
    candidates = (
        ENV_FILE,
        THIS_DIR.parent / "convert" / ".env",
        Path.cwd() / "convert_v3" / ".env",
        Path.cwd() / "convert" / ".env",
        Path.cwd() / ".env",
    )
    for path in candidates:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        return


load_dotenv()


PROVIDER_REGISTRY: Dict[str, Dict[str, Any]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-v4-pro",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen3.8-flash",
    },
    "gemini": {
        "base_url": "",
        "default_model": "gemini-3.8-flash",
    },
}


GEMINI_LEVEL_BY_EFFORT = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "max": "high",
}
GEMINI_25_BUDGET_BY_EFFORT = {
    "low": 1024,
    "medium": 8192,
    "high": 24576,
    "max": 24576,
}


def resolve_gemini_thinking(
    model: str,
    thinking_enabled: bool,
    thinking_effort: Optional[str],
) -> Dict[str, Any]:
    """Build one valid Gemini ThinkingConfig payload for the selected model."""
    normalized_model = model.lower()
    effort = (thinking_effort or "medium").strip().lower()
    if thinking_enabled and effort not in GEMINI_LEVEL_BY_EFFORT:
        valid = ", ".join(GEMINI_LEVEL_BY_EFFORT)
        raise ValueError(
            f"Unsupported Gemini thinking effort '{thinking_effort}'. "
            f"Use one of: {valid}."
        )

    if "gemini-2.5" in normalized_model:
        if not thinking_enabled:
            if "pro" in normalized_model:
                raise ValueError(
                    f"{model} does not support disabling thinking. "
                    "Set reason_effort or select a Gemini 2.5 Flash model."
                )
            return {"thinking_budget": 0, "include_thoughts": False}
        return {
            "thinking_budget": GEMINI_25_BUDGET_BY_EFFORT[effort],
            "include_thoughts": False,
        }

    if "gemini-3" in normalized_model:
        if not thinking_enabled:
            raise ValueError(
                f"{model} does not support a guaranteed thinking-off mode. "
                "Set reason_effort or select Gemini 2.5 Flash, where a "
                "thinking budget of zero is supported."
            )
        return {
            "thinking_level": GEMINI_LEVEL_BY_EFFORT[effort],
            "include_thoughts": False,
        }

    raise ValueError(
        f"Cannot apply explicit thinking control to unrecognized Gemini model "
        f"'{model}'. Use a Gemini 2.5 or Gemini 3 model name."
    )


def thinking_from_effort(reason_effort: Any) -> tuple[bool, Optional[str]]:
    if reason_effort is None:
        return False, None
    if isinstance(reason_effort, bool):
        return reason_effort, None
    text = str(reason_effort).strip()
    if not text or text.lower() in {"off", "none", "false", "0"}:
        return False, None
    return True, text


@dataclass(frozen=True)
class LlmCallConfig:
    """Resolved settings for one pipeline stage."""

    provider: str
    api_key: str
    llm: str
    max_token: int
    reason_effort: Optional[str]
    temperature: float
    base_url: str
    thinking_enabled: bool
    label: str

    @property
    def max_tokens(self) -> int:
        return self.max_token

    @property
    def thinking_effort(self) -> Optional[str]:
        return self.reason_effort


@dataclass
class PipelineConfig:
    stages: Dict[str, LlmCallConfig]
    max_retries: int = 3
    concurrency: int = 8
    save_intermediates: bool = False
    intermediates_dir: Optional[Path] = None
    _clients: Dict[Tuple[str, str, str], Any] = field(default_factory=dict, repr=False)

    def get_stage_config(self, stage_name: str) -> LlmCallConfig:
        if stage_name in self.stages:
            return self.stages[stage_name]
        if stage_name == "stage6_surface_repair":
            return self.stages["stage6_surface_generation"]
        valid = ", ".join(KNOWN_STAGES)
        raise ValueError(f"Unknown stage '{stage_name}'. Valid convert_v3 stages: {valid}")

    def output_kind(self, stage_name: str) -> str:
        return "json" if stage_name in JSON_STAGES else "text"

    def get_gemini_thinking(self, stage_name: str) -> Dict[str, Any]:
        stage = self.get_stage_config(stage_name)
        if stage.provider != "gemini":
            raise ValueError("Gemini thinking settings requested for a non-Gemini provider")
        return resolve_gemini_thinking(
            stage.llm,
            stage.thinking_enabled,
            stage.reason_effort,
        )

    def get_client(self, stage_name: str) -> Any:
        stage = self.get_stage_config(stage_name)
        cache_key = (stage.provider, stage.api_key, stage.base_url)
        cached = self._clients.get(cache_key)
        if cached is not None:
            return cached
        client = _create_client(stage.provider, stage.api_key, stage.base_url)
        self._clients[cache_key] = client
        return client


def _create_client(provider: str, api_key: str, base_url: str) -> Any:
    if provider == "gemini":
        try:
            from google import genai
        except ImportError as exc:
            raise RuntimeError(
                "Gemini support requires google-genai. Install it with: "
                "pip install -U google-genai"
            ) from exc
        return genai.Client(api_key=api_key)
    return AsyncOpenAI(api_key=api_key, base_url=base_url or None)
