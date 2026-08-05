#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Multi-stage medical dialogue conversion pipeline.

Five-stage architecture:
  Layer 1 (Understanding):
    Stage 1 — Fact Lock:       extract immutable facts as structured JSON
    Stage 2 — Scene Adaptation: classify scenario + plan online→offline migration
    Stage 3 — Turn Planning:    create dialogue skeleton with intents

  Layer 2 (Expression):
    Stage 4 — Surface Realization: generate natural spoken dialogue
    Stage 5 — Validator + Repair:  check rules, send failures back to Stage 4

Usage:
  python -m convert.pipeline \
    --input scripts-clean.jsonl \
    --output scripts-convert-v4.jsonl \
    --provider deepseek \
    --sel-ids 1283,1054 \
    --save-intermediates
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from loguru import logger
from tqdm import tqdm

from .config import (
    PipelineConfig,
    PROVIDER_REGISTRY,
    create_config_from_args,
)
from .utils import (
    async_call_llm_structured,
    call_llm_structured,
    extract_json_object,
    load_prompt_stripped,
    retry_with_backoff,
    select_audio_refs,
)

# ---------------------------------------------------------------------------
# Prompt loading (cached at module level)
# ---------------------------------------------------------------------------

_PROMPT_CACHE: Dict[str, str] = {}


def _get_prompt(name: str) -> str:
    """Load and cache a prompt file."""
    if name not in _PROMPT_CACHE:
        _PROMPT_CACHE[name] = load_prompt_stripped(name)
    return _PROMPT_CACHE[name]


# ---------------------------------------------------------------------------
# Stage implementations
# ---------------------------------------------------------------------------


def _llm_call(
    stage_name: str,
    user_content: str,
    config: PipelineConfig,
    system_prompt: str = "",
) -> Dict[str, Any]:
    """Unified LLM call for a pipeline stage."""
    stage_cfg = config.get_stage_config(stage_name)
    model = config.get_model_for_stage(stage_name)
    client = config.create_client()

    messages: List[Dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_content})

    logger.info(
        f"[{stage_cfg.label}] model={model} effort={stage_cfg.thinking_effort} "
        f"temp={stage_cfg.temperature}"
    )

    result = call_llm_structured(
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
    return result


# --- Stage 1: Fact Lock ---

def stage1_fact_lock(record: Dict[str, Any], config: PipelineConfig) -> Dict[str, Any]:
    """Extract immutable facts from the original dialogue."""
    prompt_template = _get_prompt("stage1_fact_lock")
    user_content = (
        prompt_template
        + "\n\n## 要分析的对话\n\n```json\n"
        + json.dumps(record, ensure_ascii=False)
        + "\n```"
    )
    return _llm_call(
        "stage1_fact_lock",
        user_content,
        config,
        system_prompt="你是一个医疗对话事实抽取器。只提取不可变事实，不创作任何新内容。",
    )


# --- Stage 2: Scene Adaptation ---

def stage2_scene_adaptation(
    record: Dict[str, Any],
    facts: Dict[str, Any],
    config: PipelineConfig,
) -> Dict[str, Any]:
    """Classify scenario type and plan online→offline migration."""
    prompt_template = _get_prompt("stage2_scene_adaptation")
    input_data = {
        "original_dialogue": record,
        "fact_lock": facts,
    }
    user_content = (
        prompt_template
        + "\n\n## 输入数据\n\n```json\n"
        + json.dumps(input_data, ensure_ascii=False)
        + "\n```"
    )
    return _llm_call(
        "stage2_scene_adaptation",
        user_content,
        config,
        system_prompt="你是一个医疗对话场景分析器。只做场景分类和迁移方案，不写改写句子。",
    )


# --- Stage 3: Turn Planning ---

def stage3_turn_planning(
    record: Dict[str, Any],
    facts: Dict[str, Any],
    scene: Dict[str, Any],
    config: PipelineConfig,
) -> Dict[str, Any]:
    """Create a turn-by-turn dialogue skeleton."""
    prompt_template = _get_prompt("stage3_turn_planning")
    input_data = {
        "original_dialogue": record,
        "fact_lock": facts,
        "scene_adaptation": scene,
    }
    user_content = (
        prompt_template
        + "\n\n## 输入数据\n\n```json\n"
        + json.dumps(input_data, ensure_ascii=False)
        + "\n```"
    )
    return _llm_call(
        "stage3_turn_planning",
        user_content,
        config,
        system_prompt="你是一个对话结构规划器。只规划话轮结构，不写对话文本。严格遵守硬约束。",
    )


# --- Stage 4: Surface Realization ---

def stage4_surface_realization(
    record: Dict[str, Any],
    facts: Dict[str, Any],
    scene: Dict[str, Any],
    turn_plan: Dict[str, Any],
    config: PipelineConfig,
    repair_targets: Optional[List[Dict[str, Any]]] = None,
    previous_dialogue: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate natural spoken dialogue from the turn plan.

    When repair_targets is provided, only rewrites the failed turns
    rather than regenerating the entire dialogue.
    """
    prompt_template = _get_prompt("stage4_surface_realization")
    input_data = {
        "original_dialogue": record,
        "fact_lock": facts,
        "scene_adaptation": scene,
        "turn_plan": turn_plan,
    }

    if repair_targets and previous_dialogue:
        # Repair mode: only fix specific turns
        input_data["repair_mode"] = True
        input_data["previous_dialogue"] = previous_dialogue
        input_data["repair_targets"] = repair_targets
        system_prompt = (
            "你是一个中文医疗对话转录员。现在是修复模式：主要修改标记出的有问题的 turn，"
            "可以轻微调整被修复turn前后各1个turn的表达使对话流畅。严格遵循修复建议。"
        )
    else:
        system_prompt = (
            "你是一个中文医疗对话转录员。你的任务是让对话读起来像真实的门诊录音转文字。"
            "两个说话人都可能有结巴、嘴瓢、重复和自我纠正。参考prompt中的真实转录示例。"
        )

    user_content = (
        prompt_template
        + "\n\n## 输入数据\n\n```json\n"
        + json.dumps(input_data, ensure_ascii=False)
        + "\n```"
    )
    return _llm_call("stage4_surface_realization", user_content, config, system_prompt=system_prompt)


# --- Stage 5: Validator ---

def stage5_validate(
    dialogue: Dict[str, Any],
    facts: Dict[str, Any],
    turn_plan: Dict[str, Any],
    config: PipelineConfig,
) -> Dict[str, Any]:
    """Validate the generated dialogue against structural rules."""
    prompt_template = _get_prompt("stage5_validator")
    input_data = {
        "generated_dialogue": dialogue,
        "fact_lock": facts,
        "turn_plan": turn_plan,
    }
    user_content = (
        prompt_template
        + "\n\n## 输入数据\n\n```json\n"
        + json.dumps(input_data, ensure_ascii=False)
        + "\n```"
    )
    return _llm_call(
        "stage5_validator",
        user_content,
        config,
        system_prompt="你是一个医疗对话质量审核器。只做判定，不做创作。修复建议必须精确到具体 turn。",
    )


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------

MAX_REPAIR_ATTEMPTS = 3


def run_pipeline(record: Dict[str, Any], config: PipelineConfig) -> Dict[str, Any]:
    """Run the full 5-stage pipeline on a single dialogue record.

    Returns the final result dict with keys:
      - dialogue_id, source, meta, dialogue (the rewritten dialogue)
      - audio_refs (selected reference audio paths with prompt texts)
      - validation (final Stage 5 verdict)
      - intermediates (dict of all stage outputs, if save_intermediates)
    """
    dialogue_id = record.get("dialogue_id") or record.get("id", "unknown")
    intermediates: Dict[str, Any] = {}

    logger.info(f"=== Processing dialogue {dialogue_id} ===")

    # ---- Layer 1: Understanding ----

    logger.info(f"[{dialogue_id}] Stage 1: Fact Lock")
    facts = stage1_fact_lock(record, config)
    intermediates["stage1_fact_lock"] = facts

    logger.info(f"[{dialogue_id}] Stage 2: Scene Adaptation")
    scene = stage2_scene_adaptation(record, facts, config)
    intermediates["stage2_scene_adaptation"] = scene

    logger.info(f"[{dialogue_id}] Stage 3: Turn Planning")
    turn_plan = stage3_turn_planning(record, facts, scene, config)
    intermediates["stage3_turn_planning"] = turn_plan

    # ---- Layer 2: Expression ----

    logger.info(f"[{dialogue_id}] Stage 4: Surface Realization")
    dialogue = stage4_surface_realization(record, facts, scene, turn_plan, config)
    intermediates["stage4_initial"] = dialogue

    # ---- Repair loop ----

    validation: Dict[str, Any] = {"verdict": "pass", "checks": [], "repair_targets": [], "summary": ""}
    for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
        logger.info(f"[{dialogue_id}] Stage 5: Validation (attempt {attempt})")
        validation = stage5_validate(dialogue, facts, turn_plan, config)
        intermediates[f"stage5_attempt_{attempt}"] = validation

        if validation.get("verdict") == "pass":
            logger.info(f"[{dialogue_id}] ✅ Validation passed")
            break

        repair_targets = validation.get("repair_targets", [])
        if not repair_targets:
            logger.warning(f"[{dialogue_id}] Validation failed but no repair targets — breaking loop")
            break

        logger.info(
            f"[{dialogue_id}] 🔧 Repairing {len(repair_targets)} issues (attempt {attempt})"
        )
        dialogue = stage4_surface_realization(
            record, facts, scene, turn_plan, config,
            repair_targets=repair_targets,
            previous_dialogue=dialogue,
        )
        intermediates[f"stage4_repair_{attempt}"] = dialogue

    # ---- Build result ----
    patient_sex = record.get("meta", {}).get("sex")
    audio_refs = select_audio_refs(patient_sex, config.audio_map)

    result = {
        "dialogue_id": dialogue.get("dialogue_id", dialogue_id),
        "source": dialogue.get("source", record.get("source", "")),
        "meta": dialogue.get("meta", record.get("meta", {})),
        "dialogue": dialogue.get("dialogue", []),
        "audio_refs": audio_refs,
        "validation_verdict": validation.get("verdict", "unknown"),
    }

    if validation.get("verdict") != "pass":
        logger.warning(
            f"[{dialogue_id}] ⚠️ Validation did not pass after {MAX_REPAIR_ATTEMPTS} repair attempts"
        )
        result["validation_failed"] = True

    if config.save_intermediates:
        result["intermediates"] = intermediates
        _save_intermediates(dialogue_id, intermediates, config)

    return result


# ---------------------------------------------------------------------------
# Async pipeline (per-dialogue same as sync, but using AsyncOpenAI)
# ---------------------------------------------------------------------------

async def _async_llm_call(
    stage_name: str,
    user_content: str,
    config: PipelineConfig,
    client: "AsyncOpenAI",
    system_prompt: str = "",
) -> Dict[str, Any]:
    """Async unified LLM call for a pipeline stage."""
    from openai import AsyncOpenAI  # noqa: F811

    stage_cfg = config.get_stage_config(stage_name)
    model = config.get_model_for_stage(stage_name)

    messages: List[Dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_content})

    logger.info(
        f"[{stage_cfg.label}] model={model} effort={stage_cfg.thinking_effort} "
        f"temp={stage_cfg.temperature}"
    )

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


async def async_run_pipeline(
    record: Dict[str, Any],
    config: PipelineConfig,
) -> Dict[str, Any]:
    """Async version of run_pipeline()."""
    client = config.create_async_client()
    dialogue_id = record.get("dialogue_id") or record.get("id", "unknown")
    intermediates: Dict[str, Any] = {}

    # ---- Layer 1: Understanding ----
    p1 = _get_prompt("stage1_fact_lock")
    facts = await _async_llm_call(
        "stage1_fact_lock",
        p1 + "\n\n## 要分析的对话\n\n```json\n" + json.dumps(record, ensure_ascii=False) + "\n```",
        config, client,
        system_prompt="你是一个医疗对话事实抽取器。只提取不可变事实。",
    )
    intermediates["stage1_fact_lock"] = facts

    p2 = _get_prompt("stage2_scene_adaptation")
    scene = await _async_llm_call(
        "stage2_scene_adaptation",
        p2 + "\n\n## 输入数据\n\n```json\n" + json.dumps({"original_dialogue": record, "fact_lock": facts}, ensure_ascii=False) + "\n```",
        config, client,
        system_prompt="你是一个医疗对话场景分析器。只做场景分类和迁移方案。",
    )
    intermediates["stage2_scene_adaptation"] = scene

    p3 = _get_prompt("stage3_turn_planning")
    turn_plan = await _async_llm_call(
        "stage3_turn_planning",
        p3 + "\n\n## 输入数据\n\n```json\n" + json.dumps({"original_dialogue": record, "fact_lock": facts, "scene_adaptation": scene}, ensure_ascii=False) + "\n```",
        config, client,
        system_prompt="你是一个对话结构规划器。只规划话轮结构，不写对话文本。",
    )
    intermediates["stage3_turn_planning"] = turn_plan

    # ---- Layer 2: Expression ----
    p4 = _get_prompt("stage4_surface_realization")
    dialogue = await _async_llm_call(
        "stage4_surface_realization",
        p4 + "\n\n## 输入数据\n\n```json\n" + json.dumps({"original_dialogue": record, "fact_lock": facts, "scene_adaptation": scene, "turn_plan": turn_plan}, ensure_ascii=False) + "\n```",
        config, client,
        system_prompt="你是一个中文医疗对话转录员。让对话读起来像真实门诊录音转文字。",
    )
    intermediates["stage4_initial"] = dialogue

    # ---- Repair loop ----
    validation: Dict[str, Any] = {"verdict": "pass", "checks": [], "repair_targets": [], "summary": ""}
    for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
        p5 = _get_prompt("stage5_validator")
        validation = await _async_llm_call(
            "stage5_validator",
            p5 + "\n\n## 输入数据\n\n```json\n" + json.dumps({"generated_dialogue": dialogue, "fact_lock": facts, "turn_plan": turn_plan}, ensure_ascii=False) + "\n```",
            config, client,
            system_prompt="你是一个医疗对话质量审核器。只做判定，不做创作。",
        )
        intermediates[f"stage5_attempt_{attempt}"] = validation

        if validation.get("verdict") == "pass":
            break

        repair_targets = validation.get("repair_targets", [])
        if not repair_targets:
            break

        logger.info(f"[{dialogue_id}] 🔧 Repairing {len(repair_targets)} issues (attempt {attempt})")
        dialogue = await _async_llm_call(
            "stage4_surface_realization",
            p4 + "\n\n## 输入数据\n\n```json\n" + json.dumps({
                "original_dialogue": record, "fact_lock": facts,
                "scene_adaptation": scene, "turn_plan": turn_plan,
                "repair_mode": True, "previous_dialogue": dialogue,
                "repair_targets": repair_targets,
            }, ensure_ascii=False) + "\n```",
            config, client,
            system_prompt="你是一个中文医疗对话转录员。修复模式：只修改标记的turn，可轻微调整前后各1个turn。",
        )
        intermediates[f"stage4_repair_{attempt}"] = dialogue

    # Audio refs (non-LLM)
    patient_sex = record.get("meta", {}).get("sex")
    audio_refs = select_audio_refs(patient_sex, config.audio_map)

    result = {
        "dialogue_id": dialogue.get("dialogue_id", dialogue_id),
        "source": dialogue.get("source", record.get("source", "")),
        "meta": dialogue.get("meta", record.get("meta", {})),
        "dialogue": dialogue.get("dialogue", []),
        "audio_refs": audio_refs,
        "validation_verdict": validation.get("verdict", "unknown"),
    }

    if validation.get("verdict") != "pass":
        logger.warning(
            f"[{dialogue_id}] ⚠️ Validation did not pass after {MAX_REPAIR_ATTEMPTS} repair attempts"
        )
        result["validation_failed"] = True

    if config.save_intermediates:
        _save_intermediates(dialogue_id, intermediates, config)

    return result


def _save_intermediates(
    dialogue_id: Any,
    intermediates: Dict[str, Any],
    config: PipelineConfig,
) -> None:
    """Save intermediate stage outputs to disk for inspection."""
    if not config.intermediates_dir:
        return
    out_dir = config.intermediates_dir / str(dialogue_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    for key, value in intermediates.items():
        path = out_dir / f"{key}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
    logger.info(f"Intermediates saved to {out_dir}")


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------


def parse_scripts_file(path: Path) -> List[Dict[str, Any]]:
    """Read a JSONL file and return valid records."""
    entries: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if isinstance(entry, dict):
                    entries.append(entry)
                else:
                    logger.warning(f"Skipping non-dict at {path}:{line_number}")
            except json.JSONDecodeError as exc:
                logger.warning(f"Skipping invalid JSON at {path}:{line_number}: {exc}")
    return entries


def filter_by_ids(
    entries: List[Dict[str, Any]],
    sel_ids: Optional[Set[int]],
) -> List[Dict[str, Any]]:
    """Filter entries by selected dialogue IDs."""
    if sel_ids is None:
        return entries
    filtered = []
    for entry in entries:
        eid = entry.get("dialogue_id") or entry.get("id") or entry.get("script_id")
        if eid in sel_ids:
            filtered.append(entry)
    return filtered


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-stage medical dialogue conversion pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", required=True, help="Path to input JSONL (e.g., scripts-clean.jsonl)")
    parser.add_argument("--output", required=True, help="Path to output JSONL")
    parser.add_argument(
        "--provider", default=None, choices=["deepseek", "qwen"],
        help="LLM provider (default: deepseek, or FYP_CONVERT_PROVIDER env)"
    )
    parser.add_argument("--model", default=None, help="Model name override (or FYP_CONVERT_MODEL env)")
    parser.add_argument("--base-url", default=None, help="API base URL override (or FYP_CONVERT_BASE_URL env)")
    parser.add_argument("--api-key", default=None, help="API key (or set env var)")
    parser.add_argument("--no-thinking", action="store_true", help="Disable thinking mode globally")
    parser.add_argument("--max-tokens", type=int, default=16384, help="Max tokens per LLM call")
    parser.add_argument("--max-retry", type=int, default=3, help="Max retries per LLM call")
    parser.add_argument(
        "--concurrency", type=int, default=32,
        help="Number of dialogues to process in parallel (default: 8)"
    )
    parser.add_argument(
        "--sel-ids", type=lambda s: {int(x) for x in s.split(",") if x.strip()},
        default=None, help="Comma-separated dialogue IDs to process"
    )
    parser.add_argument("--save-intermediates", action="store_true", help="Save all stage outputs to disk")
    parser.add_argument(
        "--audio-config", type=Path, default=None,
        help="Path to convert.json audio config"
    )
    parser.add_argument(
        "--planner-model", type=str, default=None,
        help="Model for Stages 1-3 (default: same as --model)"
    )
    parser.add_argument(
        "--writer-model", type=str, default=None,
        help="Model for Stage 4 (default: same as --model)"
    )
    parser.add_argument(
        "--judge-model", type=str, default=None,
        help="Model for Stage 5 (default: same as --model)"
    )
    parser.add_argument(
        "--stage-effort", type=str, nargs="*", default=None,
        help="Per-stage effort overrides, e.g. stage4_surface_realization=max stage5_validator=low"
    )
    parser.add_argument(
        "--stage-temperature", type=str, nargs="*", default=None,
        help="Per-stage temperature overrides, e.g. stage4_surface_realization=0.6"
    )
    args = parser.parse_args()

    # Validate input
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build config
    config = create_config_from_args(args)

    # Load entries
    entries = parse_scripts_file(input_path)
    logger.info(f"Loaded {len(entries)} records from {input_path}")

    # Filter
    if args.sel_ids:
        entries = filter_by_ids(entries, args.sel_ids)
        logger.info(f"Filtered to {len(entries)} records (IDs: {args.sel_ids})")

    if not entries:
        logger.warning("No records to process")
        return

    # Process
    concurrency = getattr(args, "concurrency", 1)
    if concurrency > 1:
        asyncio.run(_async_main(entries, config, output_path, concurrency))
    else:
        _sync_main(entries, config, output_path)


def _sync_main(
    entries: List[Dict[str, Any]],
    config: PipelineConfig,
    output_path: Path,
) -> None:
    """Sequential processing (original path)."""
    kept = 0
    failed = 0
    total = len(entries)

    invalid_path = output_path.with_suffix("")  # strips .jsonl
    invalid_path = Path(str(invalid_path) + "_invalid.jsonl")

    with output_path.open("w", encoding="utf-8") as fout, \
         invalid_path.open("w", encoding="utf-8") as inv_fout:
        for record in tqdm(entries, desc="Converting", unit="dialogue"):
            dialogue_id = record.get("dialogue_id") or record.get("id", "unknown")
            try:
                result = run_pipeline(record, config)
                output_record = {
                    "dialogue_id": result["dialogue_id"],
                    "source": result["source"],
                    "meta": result["meta"],
                    "dialogue": result["dialogue"],
                }
                if result.get("validation_failed"):
                    inv_fout.write(json.dumps(output_record, ensure_ascii=False) + "\n")
                    inv_fout.flush()
                    failed += 1
                else:
                    fout.write(json.dumps(output_record, ensure_ascii=False) + "\n")
                    fout.flush()
                    kept += 1
            except Exception as exc:
                failed += 1
                logger.error(f"[{dialogue_id}] Pipeline failed: {exc}")

    logger.info(f"Done. kept={kept}/{total}, failed={failed}/{total}, output={output_path}, invalid={invalid_path}")


async def _async_main(
    entries: List[Dict[str, Any]],
    config: PipelineConfig,
    output_path: Path,
    concurrency: int,
) -> None:
    """Async parallel processing with semaphore-based concurrency."""
    sem = asyncio.Semaphore(concurrency)
    total = len(entries)
    kept = 0
    failed = 0
    lock = asyncio.Lock()

    # Pre-open output files
    invalid_path = Path(str(output_path.with_suffix("")) + "_invalid.jsonl")
    fout = output_path.open("w", encoding="utf-8")
    inv_fout = invalid_path.open("w", encoding="utf-8")

    async def process_one(record: Dict[str, Any]) -> None:
        nonlocal kept, failed
        dialogue_id = record.get("dialogue_id") or record.get("id", "unknown")
        async with sem:
            try:
                result = await async_run_pipeline(record, config)
                output_record = {
                    "dialogue_id": result["dialogue_id"],
                    "source": result["source"],
                    "meta": result["meta"],
                    "dialogue": result["dialogue"],
                }
                async with lock:
                    if result.get("validation_failed"):
                        inv_fout.write(json.dumps(output_record, ensure_ascii=False) + "\n")
                        inv_fout.flush()
                        failed += 1
                    else:
                        fout.write(json.dumps(output_record, ensure_ascii=False) + "\n")
                        fout.flush()
                        kept += 1
            except Exception as exc:
                async with lock:
                    failed += 1
                logger.error(f"[{dialogue_id}] Pipeline failed: {exc}")

    tasks = [process_one(r) for r in entries]
    for coro in tqdm(asyncio.as_completed(tasks), total=total, desc="Converting", unit="dialogue"):
        await coro

    fout.close()
    inv_fout.close()
    logger.info(f"Done. kept={kept}/{total}, failed={failed}/{total}, output={output_path}, invalid={invalid_path}")


if __name__ == "__main__":
    main()
