#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Configuration for the convert_v2 planner–generator pipeline.

Launch flags, providers, and environment keys match ``convert/``. Intermediate
stages emit compact line blocks; only the writer and judge return JSON.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Optional

from openai import AsyncOpenAI


THIS_DIR = Path(__file__).resolve().parent
ENV_FILE = THIS_DIR / ".env"


def load_dotenv() -> None:
    """Load the first available project .env without an extra dependency."""
    candidates = (
        ENV_FILE,
        Path.cwd() / "convert_v2" / ".env",
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
        "default_model": "gemini-3.7-flash",
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

PLANNER_STAGES = {
    "stage1_clinical_contract",
    "stage2_encounter_plan",
    "stage3_spoken_base",
    "stage4_disfluency_plan",
    "stage1_clinical_contract_repair",
    "stage2_encounter_plan_repair",
    "stage3_spoken_base_repair",
}
WRITER_STAGES = {"stage5_surface_generation"}
JUDGE_STAGES = {"stage6_validator"}
JSON_STAGES = {
    "stage0_meta_inference",
    "stage5_surface_generation",
    "stage6_validator",
}


def resolve_gemini_thinking(
    model: str,
    thinking_enabled: bool,
    thinking_effort: Optional[str],
) -> Dict[str, Any]:
    """Build one valid Gemini ThinkingConfig payload for the selected model."""
    normalized_model = model.lower()
    effort = (thinking_effort or "medium").strip().lower()
    if effort not in GEMINI_LEVEL_BY_EFFORT:
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
                    "Remove --no-thinking or select a Gemini 2.5 Flash model."
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
                "Remove --no-thinking or select Gemini 2.5 Flash, where a "
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


@dataclass(frozen=True)
class StageRoleConfig:
    """LLM settings for one semantic role in convert_v2."""

    temperature: float
    thinking_effort: Optional[str]
    max_tokens: int
    label: str


STAGE_DEFAULTS: Dict[str, StageRoleConfig] = {
    "stage0_meta_inference": StageRoleConfig(0.1, "low", 4096, "Meta Inference"),
    "stage1_clinical_contract": StageRoleConfig(0.15, "high", 65536, "Clinical Contract"),
    "stage2_encounter_plan": StageRoleConfig(0.65, "high", 65536, "Encounter Plan"),
    "stage3_spoken_base": StageRoleConfig(0.1, "high", 65536, "Spoken Base"),
    "stage4_disfluency_plan": StageRoleConfig(0.1, "medium", 65536, "Disfluency Plan"),
    "stage5_surface_generation": StageRoleConfig(
        0.1, "medium", 65536, "Surface Generation"
    ),
    "stage6_validator": StageRoleConfig(0.1, "medium", 65536, "Validator"),
    "stage1_clinical_contract_repair": StageRoleConfig(
        0.1, "high", 65536, "Clinical Contract Repair"
    ),
    "stage2_encounter_plan_repair": StageRoleConfig(
        0.2, "high", 65536, "Encounter Plan Repair"
    ),
    "stage3_spoken_base_repair": StageRoleConfig(
        0.2, "high", 65536, "Spoken Base Repair"
    ),
}


@dataclass
class StageOverride:
    """Only supplied values override a stage default."""

    temperature: Optional[float] = None
    thinking_effort: Optional[str] = None


@dataclass
class PipelineConfig:
    provider: str
    model: str
    base_url: str
    api_key: str
    planner_model: Optional[str] = None
    writer_model: Optional[str] = None
    judge_model: Optional[str] = None
    thinking_enabled: bool = True
    max_tokens: int = 16384
    max_retries: int = 3
    save_intermediates: bool = False
    intermediates_dir: Optional[Path] = None
    stage_overrides: Dict[str, StageOverride] = field(default_factory=dict)

    def get_stage_config(self, stage_name: str) -> StageRoleConfig:
        base = STAGE_DEFAULTS[stage_name]
        override = self.stage_overrides.get(stage_name)
        if override is None:
            return replace(base, max_tokens=min(base.max_tokens, self.max_tokens))
        return StageRoleConfig(
            temperature=(
                override.temperature if override.temperature is not None else base.temperature
            ),
            thinking_effort=override.thinking_effort or base.thinking_effort,
            max_tokens=min(base.max_tokens, self.max_tokens),
            label=base.label,
        )

    def get_model_for_stage(self, stage_name: str) -> str:
        if stage_name in PLANNER_STAGES:
            return self.planner_model or self.model
        if stage_name in WRITER_STAGES:
            return self.writer_model or self.model
        if stage_name in JUDGE_STAGES:
            return self.judge_model or self.model
        return self.model

    def output_kind(self, stage_name: str) -> str:
        return "json" if stage_name in JSON_STAGES else "text"

    def get_gemini_thinking(self, stage_name: str) -> Dict[str, Any]:
        if self.provider != "gemini":
            raise ValueError("Gemini thinking settings requested for a non-Gemini provider")
        stage = self.get_stage_config(stage_name)
        return resolve_gemini_thinking(
            self.get_model_for_stage(stage_name),
            self.thinking_enabled,
            stage.thinking_effort,
        )

    def create_async_client(self) -> Any:
        if self.provider == "gemini":
            try:
                from google import genai
            except ImportError as exc:
                raise RuntimeError(
                    "Gemini support requires google-genai. Install it with: "
                    "pip install -U google-genai"
                ) from exc
            return genai.Client(api_key=self.api_key)
        return AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)


def _parse_stage_overrides(args: Any) -> Dict[str, StageOverride]:
    overrides: Dict[str, StageOverride] = {}

    def get_override(stage_name: str) -> StageOverride:
        if stage_name not in STAGE_DEFAULTS:
            valid = ", ".join(sorted(STAGE_DEFAULTS))
            raise ValueError(f"Unknown stage '{stage_name}'. Valid convert_v2 stages: {valid}")
        return overrides.setdefault(stage_name, StageOverride())

    for item in getattr(args, "stage_effort", None) or []:
        stage, sep, effort = item.partition("=")
        if not sep or not stage or not effort:
            raise ValueError(f"Invalid --stage-effort '{item}', expected stage=effort")
        get_override(stage).thinking_effort = effort

    for item in getattr(args, "stage_temperature", None) or []:
        stage, sep, value = item.partition("=")
        if not sep or not stage or not value:
            raise ValueError(
                f"Invalid --stage-temperature '{item}', expected stage=temperature"
            )
        get_override(stage).temperature = float(value)

    return overrides


def create_config_from_args(args: Any) -> PipelineConfig:
    """Create a config from the current argparse namespace."""
    provider = getattr(args, "provider", None) or os.getenv(
        "FYP_CONVERT_PROVIDER", "deepseek"
    )
    if provider not in PROVIDER_REGISTRY:
        raise ValueError(f"Unknown provider: {provider}")

    provider_info = PROVIDER_REGISTRY[provider]
    api_key = getattr(args, "api_key", None) or os.getenv("FYP_CONVERT_API_KEY", "")
    if provider == "gemini":
        api_key = api_key or os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        env_hint = (
            "GOOGLE_API_KEY or FYP_CONVERT_API_KEY"
            if provider == "gemini"
            else "FYP_CONVERT_API_KEY"
        )
        raise RuntimeError(f"No API key found. Set {env_hint} or pass --api-key.")

    model = (
        getattr(args, "model", None)
        or os.getenv("FYP_CONVERT_MODEL")
        or provider_info["default_model"]
    )
    thinking_enabled = not getattr(args, "no_thinking", False)
    if provider == "gemini" and not thinking_enabled:
        resolve_gemini_thinking(model, False, "medium")

    output = getattr(args, "output", None)
    intermediates_dir = None
    if getattr(args, "save_intermediates", False):
        intermediates_dir = (
            Path(output).parent / "intermediates" if output else THIS_DIR / "intermediates"
        )

    return PipelineConfig(
        provider=provider,
        model=model,
        base_url=(
            getattr(args, "base_url", None)
            or os.getenv("FYP_CONVERT_BASE_URL")
            or provider_info["base_url"]
        ),
        api_key=api_key,
        planner_model=getattr(args, "planner_model", None),
        writer_model=getattr(args, "writer_model", None),
        judge_model=getattr(args, "judge_model", None),
        thinking_enabled=thinking_enabled,
        max_tokens=getattr(args, "max_tokens", 16384),
        max_retries=getattr(args, "max_retry", 3),
        save_intermediates=bool(getattr(args, "save_intermediates", False)),
        intermediates_dir=intermediates_dir,
        stage_overrides=_parse_stage_overrides(args),
    )
