#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Configuration for the multi-stage medical dialogue conversion pipeline.

Supports DeepSeek and Qwen (DashScope) providers with per-stage thinking and
temperature settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI, OpenAI

# ---------------------------------------------------------------------------
# .env loading (no external dependency)
# ---------------------------------------------------------------------------

THIS_DIR = Path(__file__).resolve().parent
_ENV_FILE = THIS_DIR / ".env"


def _load_dotenv() -> None:
    """Load .env file into os.environ (simple, no python-dotenv dependency).

    Tries multiple candidate paths to handle different working directories.
    """
    candidates = [
        _ENV_FILE,                       # convert/.env (next to config.py)
        Path.cwd() / "convert" / ".env", # cwd/convert/.env
        Path.cwd() / ".env",             # cwd/.env
    ]
    for env_path in candidates:
        if not env_path.exists():
            continue
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        # Stop after first successful load
        break


_load_dotenv()

# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

PROVIDER_REGISTRY: Dict[str, Dict[str, Any]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-v4-pro",
        "supports_json_mode_with_thinking": True,
        "thinking_param": "extra_body.thinking.type",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen3.8-flash",
        "supports_json_mode_with_thinking": False,
        "thinking_param": "extra_body.enable_thinking",
    },
}

# Unified API key env var (set in .env)
_API_KEY_ENV = "FYP_CONVERT_API_KEY"


# ---------------------------------------------------------------------------
# Stage role definitions
# ---------------------------------------------------------------------------

@dataclass
class StageRoleConfig:
    """Per-stage LLM configuration."""
    temperature: float = 0.4
    thinking_effort: Optional[str] = None  # DeepSeek: low/high/max; Qwen qwen3.8-max: low..max
    max_tokens: int = 4096
    label: str = ""


# Default per-stage configurations (DeepSeek effort values)
# max_tokens=8192 because thinking mode easily consumes 3000+ tokens
# on reasoning, leaving insufficient room for the actual response at 4096.
STAGE_DEFAULTS: Dict[str, StageRoleConfig] = {
    "stage0_meta_inference": StageRoleConfig(
        temperature=0.1, thinking_effort="low", max_tokens=8192, label="Meta Inference"
    ),
    "stage1_fact_lock": StageRoleConfig(
        temperature=0.2, thinking_effort="high", max_tokens=32768, label="Fact Lock"
    ),
    "stage2_scene_adaptation": StageRoleConfig(
        temperature=0.2, thinking_effort="high", max_tokens=32768, label="Scene Adaptation"
    ),
    "stage3_turn_planning": StageRoleConfig(
        temperature=0.2, thinking_effort="high", max_tokens=32768, label="Turn Planning"
    ),
    "stage4_surface_realization": StageRoleConfig(
        temperature=0.5, thinking_effort="max", max_tokens=32768, label="Surface Realization"
    ),
    # Stage 5 is validator — uses its own stage config but also supports
    # a dedicated judge model if --judge-model is provided.
    "stage5_validator": StageRoleConfig(
        temperature=0.1, thinking_effort="medium", max_tokens=32768, label="Validator"
    ),
}


# ---------------------------------------------------------------------------
# Pipeline configuration
# ---------------------------------------------------------------------------

@dataclass
class PipelineConfig:
    """Complete configuration for a pipeline run."""

    # Provider
    provider: str = "deepseek"
    model: str = "deepseek-v4-pro"
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""

    # Per-role model overrides (use same model as default if not set)
    planner_model: Optional[str] = None   # Stages 1-3
    writer_model: Optional[str] = None    # Stage 4
    judge_model: Optional[str] = None     # Stage 5

    # Global settings
    thinking_enabled: bool = True
    max_tokens: int = 8192
    max_retries: int = 3

    # Input / output
    input_path: Optional[Path] = None
    output_path: Optional[Path] = None
    sel_ids: Optional[List[int]] = None
    save_intermediates: bool = False
    intermediates_dir: Optional[Path] = None

    # Per-stage overrides (keyed by stage name)
    stage_overrides: Dict[str, StageRoleConfig] = field(default_factory=dict)

    def get_stage_config(self, stage_name: str) -> StageRoleConfig:
        """Get effective config for a stage, respecting overrides."""
        base = STAGE_DEFAULTS.get(stage_name, StageRoleConfig())
        override = self.stage_overrides.get(stage_name)
        if override is not None:
            # Merge: override only non-None fields
            result = StageRoleConfig(
                temperature=override.temperature
                if override.temperature != 0.4
                else base.temperature,
                thinking_effort=override.thinking_effort or base.thinking_effort,
                max_tokens=override.max_tokens
                if override.max_tokens != 4096
                else base.max_tokens,
                label=override.label or base.label,
            )
            return result
        return base

    def get_model_for_stage(self, stage_name: str) -> str:
        """Get the model name to use for a given stage."""
        if stage_name in ("stage1_fact_lock", "stage2_scene_adaptation", "stage3_turn_planning"):
            return self.planner_model or self.model
        elif stage_name == "stage4_surface_realization":
            return self.writer_model or self.model
        elif stage_name == "stage5_validator":
            return self.judge_model or self.model
        return self.model

    def create_client(self) -> OpenAI:
        """Create a sync OpenAI client from this config."""
        return OpenAI(api_key=self.api_key, base_url=self.base_url)

    def create_async_client(self) -> AsyncOpenAI:
        """Create an async OpenAI client from this config."""
        return AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)


# ---------------------------------------------------------------------------
# Factory from CLI args
# ---------------------------------------------------------------------------

def create_config_from_args(args: Any) -> PipelineConfig:
    """Build a PipelineConfig from parsed argparse Namespace."""

    # Resolve provider: CLI arg > FYP_CONVERT_PROVIDER env > "deepseek"
    provider = args.provider or os.getenv("FYP_CONVERT_PROVIDER", "deepseek")
    provider_info = PROVIDER_REGISTRY.get(provider, PROVIDER_REGISTRY["deepseek"])

    # Resolve API key: explicit arg > FYP_CONVERT_API_KEY env var
    api_key = args.api_key or os.getenv(_API_KEY_ENV, "")
    if not api_key:
        raise RuntimeError(
            f"No API key found. Set {_API_KEY_ENV} in .env or pass --api-key."
        )

    # Resolve model: CLI arg > FYP_CONVERT_MODEL env > provider default
    model = args.model or os.getenv("FYP_CONVERT_MODEL") or provider_info["default_model"]

    # Resolve base URL: CLI arg > FYP_CONVERT_BASE_URL env > provider default
    base_url = args.base_url or os.getenv("FYP_CONVERT_BASE_URL") or provider_info["base_url"]

    # Build stage overrides from --stage-effort and --stage-temperature args
    stage_overrides: Dict[str, StageRoleConfig] = {}

    if getattr(args, "stage_effort", None):
        for item in args.stage_effort:
            stage, effort = item.split("=", 1)
            if stage not in stage_overrides:
                stage_overrides[stage] = StageRoleConfig()
            stage_overrides[stage].thinking_effort = effort

    if getattr(args, "stage_temperature", None):
        for item in args.stage_temperature:
            stage, temp = item.split("=", 1)
            if stage not in stage_overrides:
                stage_overrides[stage] = StageRoleConfig()
            stage_overrides[stage].temperature = float(temp)

    # Intermediates directory
    intermediates_dir = None
    if getattr(args, "save_intermediates", False):
        intermediates_dir = (
            Path(args.output).parent / "intermediates"
            if args.output
            else THIS_DIR / "intermediates"
        )

    return PipelineConfig(
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
        planner_model=getattr(args, "planner_model", None),
        writer_model=getattr(args, "writer_model", None),
        judge_model=getattr(args, "judge_model", None),
        thinking_enabled=not getattr(args, "no_thinking", False),
        max_tokens=getattr(args, "max_tokens", 4096),
        max_retries=getattr(args, "max_retry", 3),
        input_path=Path(args.input) if args.input else None,
        output_path=Path(args.output) if args.output else None,
        sel_ids=args.sel_ids,
        save_intermediates=bool(getattr(args, "save_intermediates", False)),
        intermediates_dir=intermediates_dir,
        stage_overrides=stage_overrides,
    )
