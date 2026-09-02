#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compact v3 medical-dialogue conversion pipeline.

Requires the existing package's config.py and utils.py. CLI arguments are kept
compatible with pipeline.py; prompts are read from v3_complete.md by default.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from loguru import logger
from tqdm import tqdm

from .config import PipelineConfig, create_config_from_args
from .utils import async_stage_llm_call, save_intermediates

MAX_REPAIR_ATTEMPTS = 3
MISSING = {"", "none", "null", "unknown", "unk", "n/a", "na", "未知"}
SYSTEM = {
    "stage0_meta_inference": "You infer only missing dialogue metadata. Return JSON only.",
    "stage1_fact_lock": "You extract immutable medical facts. Return JSON only.",
    "stage2_scene_adaptation": "You plan an offline consultation frame. Return JSON only.",
    "stage3_turn_planning": "You plan a fact-driven dialogue skeleton. Return JSON only.",
    "stage4_surface_realization": "You write a natural Chinese outpatient dialogue. Return JSON only.",
    "stage5_validator": "You audit factual fidelity and naturalness. Return JSON only.",
}


def load_prompt_book(path: Path) -> Dict[str, str]:
    text = path.read_text(encoding="utf-8")
    prompts: Dict[str, str] = {}
    marker = "<!-- STAGE: "
    for chunk in text.split(marker)[1:]:
        name, _, body = chunk.partition(" -->")
        prompts[name.strip()] = body.strip()
    required = set(SYSTEM) | {"stage4_surface_repair"}
    missing = required - prompts.keys()
    if missing:
        raise ValueError(f"Prompt book missing stages: {sorted(missing)}")
    return prompts


def missing(value: Any) -> bool:
    return value is None or (
        isinstance(value, str) and value.strip().lower() in MISSING
    )


def normalize_sex(value: Any) -> Optional[str]:
    value = str(value).strip().lower() if value is not None else ""
    if value in {"男", "male", "m", "man", "boy", "男性"}:
        return "男"
    if value in {"女", "female", "f", "woman", "girl", "女性"}:
        return "女"
    return None


def normalize_language(value: Any) -> Optional[str]:
    value = str(value).strip().lower() if value is not None else ""
    chinese_values = {
        "chinese",
        "mandarin",
        "zh",
        "zh-cn",
        "中文",
        "汉语",
        "普通话",
    }
    return "Chinese" if value in chinese_values else None


def normalize_age(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def prepare_record(
    record: Dict[str, Any],
) -> tuple[Dict[str, Any], Dict[str, Any], bool, bool, bool]:
    prepared = dict(record)
    meta = dict(record.get("meta") or {})
    sex = normalize_sex(meta.get("sex"))
    age = normalize_age(meta.get("age"))
    language = normalize_language(meta.get("language"))
    sex_missing = missing(meta.get("sex")) or sex is None
    age_missing = missing(meta.get("age")) or age is None
    language_missing = missing(meta.get("language")) or language is None

    if not sex_missing:
        meta["sex"] = sex
    if not age_missing:
        meta["age"] = age
    if not language_missing:
        meta["language"] = language
    prepared["meta"] = meta
    return prepared, meta, sex_missing, age_missing, language_missing


def merge_meta(
    base: Dict[str, Any],
    inferred: Dict[str, Any],
    sex_missing: bool,
    age_missing: bool,
    language_missing: bool,
) -> Dict[str, Any]:
    result = dict(base)

    inferred_sex = normalize_sex(inferred.get("sex"))
    inferred_age = normalize_age(inferred.get("age"))
    inferred_language = normalize_language(inferred.get("language"))

    if sex_missing and inferred_sex is not None:
        result["sex"] = inferred_sex
    if age_missing and inferred_age is not None:
        result["age"] = inferred_age
    if language_missing and inferred_language is not None:
        result["language"] = inferred_language

    return result


def final_meta(record_meta: Dict[str, Any], generated_meta: Any) -> Dict[str, Any]:
    meta = dict(record_meta or {})
    if isinstance(generated_meta, dict):
        meta.update(generated_meta)
    # Stage 4 may echo meta but it must never overwrite supplied/inferred metadata.
    meta.update(record_meta or {})
    return meta


def payload(stage: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    if stage in {"stage0_meta_inference", "stage1_fact_lock"}:
        return ctx["record"]

    if stage == "stage2_scene_adaptation":
        return {
            "original_dialogue": ctx["record"],
            "fact_lock": ctx["facts"],
        }

    if stage == "stage3_turn_planning":
        return {
            "original_dialogue": ctx["record"],
            "fact_lock": ctx["facts"],
            "scene_adaptation": ctx["scene"],
        }

    if stage == "stage4_surface_realization":
        data = {
            "original_dialogue": ctx["record"],
            "fact_lock": ctx["facts"],
            "scene_adaptation": ctx["scene"],
            "turn_plan": ctx["plan"],
        }
        if ctx.get("repair_targets"):
            data.update(
                {
                    "repair_mode": True,
                    "previous_dialogue": ctx["dialogue"],
                    "repair_targets": ctx["repair_targets"],
                }
            )
        return data

    return {
        "generated_dialogue": ctx["dialogue"],
        "fact_lock": ctx["facts"],
        "turn_plan": ctx["plan"],
    }


async def run_stage(
    stage: str,
    ctx: Dict[str, Any],
    config: PipelineConfig,
    client: Any,
    prompts: Dict[str, str],
    intermediates: Dict[str, Any],
    key: str,
) -> Dict[str, Any]:
    is_repair = stage == "stage4_surface_realization" and ctx.get("repair_targets")
    prompt_key = "stage4_surface_repair" if is_repair else stage
    input_json = json.dumps(payload(stage, ctx), ensure_ascii=False)
    text = (
        prompts[prompt_key]
        + "\n\n## Input JSON\n```json\n"
        + input_json
        + "\n```"
    )
    tqdm.write(f"[{ctx['dialogue_id']}] {stage}")
    result = await async_stage_llm_call(
        stage,
        text,
        system_prompt=SYSTEM[stage],
        config=config,
        client=client,
    )
    intermediates[key] = result
    return result


async def async_run_pipeline(
    record: Dict[str, Any],
    config: PipelineConfig,
    prompt_path: Optional[Path] = None,
) -> Dict[str, Any]:
    prompt_path = prompt_path or Path(__file__).parent / "prompts" / "v3_complete.md"
    prompts = load_prompt_book(prompt_path)
    client = config.create_async_client()
    intermediates: Dict[str, Any] = {}
    (
        prepared,
        meta_base,
        sex_missing,
        age_missing,
        language_missing,
    ) = prepare_record(record)
    dialogue_id = prepared.get("dialogue_id") or prepared.get("id", "unknown")
    ctx: Dict[str, Any] = {
        "dialogue_id": dialogue_id,
        "record": prepared,
        "repair_targets": [],
    }

    if sex_missing or age_missing or language_missing:
        inferred = await run_stage(
            "stage0_meta_inference",
            ctx,
            config,
            client,
            prompts,
            intermediates,
            "stage0_meta_inference",
        )
        ctx["record"]["meta"] = merge_meta(
            meta_base,
            inferred,
            sex_missing,
            age_missing,
            language_missing,
        )

    ctx["facts"] = await run_stage(
        "stage1_fact_lock",
        ctx,
        config,
        client,
        prompts,
        intermediates,
        "stage1_fact_lock",
    )
    ctx["scene"] = await run_stage(
        "stage2_scene_adaptation",
        ctx,
        config,
        client,
        prompts,
        intermediates,
        "stage2_scene_adaptation",
    )
    ctx["plan"] = await run_stage(
        "stage3_turn_planning",
        ctx,
        config,
        client,
        prompts,
        intermediates,
        "stage3_turn_planning",
    )
    ctx["dialogue"] = await run_stage(
        "stage4_surface_realization",
        ctx,
        config,
        client,
        prompts,
        intermediates,
        "stage4_initial",
    )

    validation: Dict[str, Any] = {"verdict": "repair"}
    for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
        validation = await run_stage(
            "stage5_validator",
            ctx,
            config,
            client,
            prompts,
            intermediates,
            f"stage5_attempt_{attempt + 1}",
        )
        if validation.get("verdict") == "pass":
            break

        ctx["repair_targets"] = validation.get("repair_targets") or []
        if not ctx["repair_targets"] or attempt == MAX_REPAIR_ATTEMPTS:
            break

        ctx["dialogue"] = await run_stage(
            "stage4_surface_realization",
            ctx,
            config,
            client,
            prompts,
            intermediates,
            f"stage4_repair_{attempt + 1}",
        )

    dialogue = ctx["dialogue"]
    result = {
        "dialogue_id": dialogue.get("dialogue_id", dialogue_id),
        "source": dialogue.get("source", record.get("source", "")),
        "meta": final_meta(ctx["record"].get("meta", {}), dialogue.get("meta")),
        "dialogue": dialogue.get("dialogue", []),
        "validation_verdict": validation.get("verdict", "unknown"),
    }
    if validation.get("verdict") != "pass":
        result["validation_failed"] = True
    if config.save_intermediates:
        save_intermediates(dialogue_id, intermediates, config.intermediates_dir)

    return result


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue

        try:
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
            else:
                logger.warning(f"Skipping non-object at {path}:{number}")
        except json.JSONDecodeError as exc:
            logger.warning(f"Skipping invalid JSON at {path}:{number}: {exc}")

    return rows


def entry_id(item: Dict[str, Any]) -> Optional[str]:
    value = item.get("dialogue_id") or item.get("id") or item.get("script_id")
    return None if value is None else str(value)


def existing_ids(path: Path) -> Set[str]:
    if not path.exists():
        return set()

    identifiers: Set[str] = set()
    for row in read_jsonl(path):
        identifier = entry_id(row)
        if identifier is not None:
            identifiers.add(identifier)
    return identifiers


async def async_main(
    entries: List[Dict[str, Any]],
    config: PipelineConfig,
    output: Path,
    concurrency: int,
    supplement: bool,
) -> None:
    invalid = output.with_name(output.stem + "_invalid.jsonl")
    mode = "a" if supplement else "w"
    sem = asyncio.Semaphore(max(1, concurrency))
    lock = asyncio.Lock()
    kept = 0
    failed = 0

    with (
        output.open(mode, encoding="utf-8") as good,
        invalid.open(mode, encoding="utf-8") as bad,
    ):
        async def one(item: Dict[str, Any]) -> None:
            nonlocal kept, failed
            async with sem:
                try:
                    result = await async_run_pipeline(item, config)
                    row = {
                        key: result[key]
                        for key in ("dialogue_id", "source", "meta", "dialogue")
                    }

                    async with lock:
                        target = bad if result.get("validation_failed") else good
                        target.write(json.dumps(row, ensure_ascii=False) + "\n")
                        target.flush()

                        if result.get("validation_failed"):
                            failed += 1
                        else:
                            kept += 1
                except Exception as exc:
                    async with lock:
                        failed += 1
                    logger.error(f"[{entry_id(item) or 'unknown'}] Pipeline failed: {exc}")

        tasks = [one(item) for item in entries]
        progress = tqdm(
            asyncio.as_completed(tasks),
            total=len(entries),
            desc="Converting",
            unit="dialogue",
        )
        for task in progress:
            await task

    tqdm.write(
        f"Done. kept={kept}/{len(entries)}, failed={failed}/{len(entries)}, "
        f"output={output}, invalid={invalid}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-stage medical dialogue conversion pipeline"
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--provider",
        default=None,
        choices=["deepseek", "qwen"],
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--no-thinking", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=16384)
    parser.add_argument("--max-retry", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument(
        "--sel-ids",
        type=lambda value: {
            int(part)
            for part in value.split(",")
            if part.strip()
        },
        default=None,
    )
    parser.add_argument("--save-intermediates", action="store_true")
    parser.add_argument("--planner-model", type=str, default=None)
    parser.add_argument("--writer-model", type=str, default=None)
    parser.add_argument("--judge-model", type=str, default=None)
    parser.add_argument("--stage-effort", type=str, nargs="*", default=None)
    parser.add_argument("--stage-temperature", type=str, nargs="*", default=None)
    parser.add_argument("--supplement", action="store_true")

    args = parser.parse_args()
    source = Path(args.input)
    output = Path(args.output)

    if not source.exists():
        logger.error(f"Input file not found: {source}")
        sys.exit(1)

    output.parent.mkdir(parents=True, exist_ok=True)
    entries = read_jsonl(source)

    if args.sel_ids is not None:
        selected: List[Dict[str, Any]] = []
        for row in entries:
            identifier = entry_id(row)
            if identifier is not None and identifier.isdigit():
                if int(identifier) in args.sel_ids:
                    selected.append(row)
        entries = selected

    if args.supplement:
        seen = existing_ids(output)
        pending: List[Dict[str, Any]] = []
        for row in entries:
            identifier = entry_id(row)
            if identifier is None or identifier not in seen:
                pending.append(row)
                if identifier is not None:
                    seen.add(identifier)
        entries = pending

    if not entries:
        logger.warning("No records to process")
        return

    config = create_config_from_args(args)
    asyncio.run(
        async_main(
            entries,
            config,
            output,
            args.concurrency,
            args.supplement,
        )
    )


if __name__ == "__main__":
    main()