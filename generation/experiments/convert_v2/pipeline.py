#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""convert_v2 planner–generator conversion pipeline.

Source wording is visible to meta inference, the clinical contract, and a
compact Stage 3 / Stage 3 repair reference. Later stages otherwise receive
previous stage text as-is and are not parsed in code.
Only the writer and judge return JSON for TTS/ASR output.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from loguru import logger
from tqdm import tqdm

from .config import PipelineConfig, create_config_from_args
from .utils import async_stage_llm_call, save_intermediates


MAX_REPAIR_ATTEMPTS = 2
MISSING = {"", "none", "null", "unknown", "unk", "n/a", "na", "未知"}
STAGES = (
    "stage0_meta_inference",
    "stage1_clinical_contract",
    "stage2_encounter_plan",
    "stage3_spoken_base",
    "stage4_disfluency_plan",
    "stage5_surface_generation",
    "stage6_validator",
)
REPAIR_STAGE = "stage5_surface_repair"
STRUCTURAL_REPAIR_STAGES = {
    "contract": "stage1_clinical_contract_repair",
    "plan": "stage2_encounter_plan_repair",
    "spoken_base": "stage3_spoken_base_repair",
}
SYSTEM = {
    "stage0_meta_inference": "Infer missing metadata only. Return one JSON object.",
    "stage1_clinical_contract": "Extract a clinical contract only. Return one [CLINICAL_CONTRACT] block.",
    "stage2_encounter_plan": "Direct a new offline encounter from the contract. Return one [ENCOUNTER_PLAN] block.",
    "stage3_spoken_base": "Write a fluent spoken base from the contract and plan. Return one [SPOKEN_BASE] block.",
    "stage4_disfluency_plan": "Plan local disfluency only. Return one [DISFLUENCY_PLAN] block.",
    "stage5_surface_generation": "Realize the disfluency plan as a Chinese outpatient transcript. Return one JSON object.",
    "stage6_validator": "Audit clinical constraints and transcript naturalness. Return one JSON object.",
    "stage1_clinical_contract_repair": "Repair the clinical contract only. Return one [CLINICAL_CONTRACT] block.",
    "stage2_encounter_plan_repair": "Repair the encounter plan only. Return one [ENCOUNTER_PLAN] block.",
    "stage3_spoken_base_repair": "Repair the spoken base only. Return one [SPOKEN_BASE] block.",
}


def load_prompt_book(path: Path) -> Dict[str, str]:
    """Read the one-file prompt book split by named HTML markers."""
    prompts: Dict[str, str] = {}
    for chunk in path.read_text(encoding="utf-8").split("<!-- STAGE: ")[1:]:
        name, separator, body = chunk.partition(" -->")
        if separator:
            prompts[name.strip()] = body.strip()
    required = set(STAGES) | {REPAIR_STAGE} | set(STRUCTURAL_REPAIR_STAGES.values())
    missing_stages = sorted(required - prompts.keys())
    if missing_stages:
        raise ValueError(
            "Prompt book missing required sections: " + ", ".join(missing_stages)
        )
    return prompts


def resolve_prompt_path(requested: Optional[str]) -> Path:
    if requested:
        return Path(requested)
    package_dir = Path(__file__).resolve().parent
    candidates = (
        package_dir / "prompts" / "v5_complete.md",
        package_dir / "v5_complete.md",
    )
    return next((path for path in candidates if path.exists()), candidates[0])


def is_missing(value: Any) -> bool:
    return value is None or (
        isinstance(value, str) and value.strip().lower() in MISSING
    )


def normalize_sex(value: Any) -> Optional[str]:
    text = str(value).strip().lower() if value is not None else ""
    if text in {"男", "male", "m", "man", "boy", "男性"}:
        return "男"
    if text in {"女", "female", "f", "woman", "girl", "女性"}:
        return "女"
    return None


def normalize_age(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def normalize_language(value: Any) -> Optional[str]:
    text = str(value).strip().lower() if value is not None else ""
    if text in {"chinese", "mandarin", "zh", "zh-cn", "中文", "汉语", "普通话"}:
        return "Chinese"
    return None


def prepare_record(
    record: Dict[str, Any],
) -> tuple[Dict[str, Any], Dict[str, Any], tuple[bool, bool, bool]]:
    prepared = dict(record)
    meta = dict(record.get("meta") or {})
    for field in ("sex", "age", "language"):
        meta.setdefault(field, None)
    sex = normalize_sex(meta.get("sex"))
    age = normalize_age(meta.get("age"))
    language = normalize_language(meta.get("language"))
    missing_flags = (
        is_missing(meta.get("sex")) or sex is None,
        is_missing(meta.get("age")) or age is None,
        is_missing(meta.get("language")) or language is None,
    )
    if not missing_flags[0]:
        meta["sex"] = sex
    if not missing_flags[1]:
        meta["age"] = age
    if not missing_flags[2]:
        meta["language"] = language
    prepared["meta"] = meta
    return prepared, meta, missing_flags


def merge_meta(
    base: Dict[str, Any],
    inferred: Dict[str, Any],
    missing_flags: tuple[bool, bool, bool],
) -> Dict[str, Any]:
    result = dict(base)
    inferred_sex = normalize_sex(inferred.get("sex"))
    inferred_age = normalize_age(inferred.get("age"))
    inferred_language = normalize_language(inferred.get("language"))
    if missing_flags[0] and inferred_sex is not None:
        result["sex"] = inferred_sex
    if missing_flags[1] and inferred_age is not None:
        result["age"] = inferred_age
    if missing_flags[2] and inferred_language is not None:
        result["language"] = inferred_language
    return result


def output_identity(context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "dialogue_id": context["dialogue_id"],
        "source": context["source"],
        "meta": context["record"].get("meta", {}),
    }


def _join_blocks(*blocks: str) -> str:
    return "\n\n".join(block.strip() for block in blocks if block and block.strip())


_SPEAKER_ABBREV = {
    "患者": "患",
    "医生": "医",
    "陪诊者": "陪",
}


def compact_source_turns(record: Dict[str, Any]) -> str:
    """Render original turns as compact speaker|text lines, not JSON."""
    lines = ["[SOURCE_TURNS]"]
    for turn in record.get("dialogue") or []:
        text = re.sub(r"\s+", " ", str(turn.get("text") or "")).strip()
        if not text:
            continue
        speaker = str(turn.get("speaker") or "").strip()
        speaker = _SPEAKER_ABBREV.get(speaker, speaker)
        if not speaker:
            continue
        lines.append(f"{speaker} | {text}")
    lines.append("[/SOURCE_TURNS]")
    return "\n".join(lines)


def _source_turns_block(context: Dict[str, Any]) -> str:
    return (
        "## Source turns (reference only)\n"
        + compact_source_turns(context["record"])
    )


def stage_user_content(
    stage: str,
    context: Dict[str, Any],
    prompt_body: str,
) -> str:
    """Assemble the user message: stage prompt plus previous outputs as raw text."""
    if stage in {"stage0_meta_inference", "stage1_clinical_contract"}:
        payload = (
            "## Input JSON\n```json\n"
            + json.dumps(context["record"], ensure_ascii=False)
            + "\n```"
        )
        return prompt_body + "\n\n" + payload

    if stage == "stage2_encounter_plan":
        prior = "## Previous stage output\n" + context["clinical_contract"]
        return prompt_body + "\n\n" + prior

    if stage == "stage3_spoken_base":
        prior = "## Previous stage outputs\n" + _join_blocks(
            context["clinical_contract"],
            context["encounter_plan"],
        )
        return prompt_body + "\n\n" + prior + "\n\n" + _source_turns_block(context)

    if stage == "stage4_disfluency_plan":
        prior = "## Previous stage outputs\n" + _join_blocks(
            context["clinical_contract"],
            context["encounter_plan"],
            context["spoken_base"],
        )
        return prompt_body + "\n\n" + prior

    if stage in STRUCTURAL_REPAIR_STAGES.values():
        repair_scope = next(
            scope for scope, repair_stage in STRUCTURAL_REPAIR_STAGES.items()
            if repair_stage == stage
        )
        previous_key = {
            "contract": "clinical_contract",
            "plan": "encounter_plan",
            "spoken_base": "spoken_base",
        }[repair_scope]
        prior_blocks = []
        if repair_scope in {"plan", "spoken_base"}:
            prior_blocks.append(context["clinical_contract"])
        if repair_scope == "spoken_base":
            prior_blocks.append(context["encounter_plan"])
        targets = [
            target for target in context["repair_targets"]
            if target.get("scope") == repair_scope
        ]
        original_input = ""
        if repair_scope == "contract":
            original_input = (
                "\n\n## Original input JSON\n```json\n"
                + json.dumps(context["record"], ensure_ascii=False)
                + "\n```"
            )
        elif repair_scope == "spoken_base":
            original_input = "\n\n" + _source_turns_block(context)
        return (
            prompt_body
            + "\n\n## Previous stage outputs\n"
            + _join_blocks(*prior_blocks)
            + "\n\n## Previous target block\n"
            + context[previous_key]
            + "\n\n## Structural repair targets\n```json\n"
            + json.dumps(targets, ensure_ascii=False)
            + "\n```"
            + original_input
        )

    identity = (
        "## Output identity JSON\n```json\n"
        + json.dumps(output_identity(context), ensure_ascii=False)
        + "\n```"
    )
    plans = "## Previous stage outputs\n" + _join_blocks(
        context["clinical_contract"],
        context["encounter_plan"],
        context["spoken_base"],
        context["disfluency_plan"],
    )
    if stage == "stage5_surface_generation":
        extra = ""
        if context.get("repair_targets"):
            extra = (
                "\n\n## Repair mode\n```json\n"
                + json.dumps(
                    {
                        "repair_mode": True,
                        "previous_dialogue": context["dialogue"],
                        "repair_targets": context["repair_targets"],
                    },
                    ensure_ascii=False,
                )
                + "\n```"
            )
        return prompt_body + "\n\n" + identity + "\n\n" + plans + extra

    generated = (
        "## Generated dialogue JSON\n```json\n"
        + json.dumps(context["dialogue"], ensure_ascii=False)
        + "\n```"
    )
    return prompt_body + "\n\n" + identity + "\n\n" + plans + "\n\n" + generated


async def run_stage(
    stage: str,
    context: Dict[str, Any],
    config: PipelineConfig,
    client: Any,
    prompts: Dict[str, str],
    intermediates: Dict[str, Any],
    saved_name: str,
) -> Any:
    is_repair = stage == "stage5_surface_generation" and context.get("repair_targets")
    prompt_key = REPAIR_STAGE if is_repair else stage
    user_content = stage_user_content(stage, context, prompts[prompt_key])
    tqdm.write(f"[{context['dialogue_id']}] {stage}")
    result = await async_stage_llm_call(
        stage,
        user_content,
        system_prompt=SYSTEM[stage],
        config=config,
        client=client,
    )
    intermediates[saved_name] = result
    return result


async def async_run_pipeline(
    record: Dict[str, Any],
    config: PipelineConfig,
    prompt_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Convert one source record through convert_v2 stages."""
    prompts = load_prompt_book(prompt_path or resolve_prompt_path(None))
    prepared, meta_base, missing_flags = prepare_record(record)
    dialogue_id = prepared.get("dialogue_id") or prepared.get("id") or "unknown"
    context: Dict[str, Any] = {
        "dialogue_id": dialogue_id,
        "source": record.get("source", ""),
        "record": prepared,
        "repair_targets": [],
    }
    intermediates: Dict[str, Any] = {}
    client = config.create_async_client()

    if any(missing_flags):
        inferred = await run_stage("stage0_meta_inference", 
                                   context, config, client, prompts, intermediates,
                                   "stage0_meta_inference",
        )
        context["record"]["meta"] = merge_meta(meta_base, inferred, missing_flags)

    context["clinical_contract"] = await run_stage(
        "stage1_clinical_contract",
        context, config, client, prompts, intermediates,
        "stage1_clinical_contract",
    )
    context["encounter_plan"] = await run_stage(
        "stage2_encounter_plan",
        context, config, client, prompts, intermediates,
        "stage2_encounter_plan",
    )
    context["spoken_base"] = await run_stage(
        "stage3_spoken_base",
        context, config, client, prompts, intermediates,
        "stage3_spoken_base",
    )
    context["disfluency_plan"] = await run_stage(
        "stage4_disfluency_plan",
        context, config, client, prompts, intermediates,
        "stage4_disfluency_plan",
    )
    context["dialogue"] = await run_stage(
        "stage5_surface_generation",
        context, config, client, prompts, intermediates,
        "stage5_initial",
    )

    validation: Dict[str, Any] = {"verdict": "repair", "repair_targets": []}
    for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
        validation = await run_stage(
            "stage6_validator",
            context, config, client, prompts, intermediates,
            f"stage6_attempt_{attempt + 1}",
        )
        if validation.get("verdict") == "pass":
            break
        if validation.get("verdict") == "fail":
            break
        raw_targets = validation.get("repair_targets") or []
        context["repair_targets"] = [
            {**target, "scope": target.get("scope", "surface")}
            for target in raw_targets
            if isinstance(target, dict)
        ]
        if not context["repair_targets"]:
            logger.error(
                "[{}] validator returned repair without usable repair targets",
                context["dialogue_id"],
            )
            validation = {
                **validation,
                "verdict": "fail",
                "failure_class": "unrepairable",
                "failed_rules": validation.get("failed_rules") or [
                    "validator_repair_targets"
                ],
            }
            break
        if attempt == MAX_REPAIR_ATTEMPTS:
            break
        structural_scopes = {
            target.get("scope")
            for target in context["repair_targets"]
            if target.get("scope") in STRUCTURAL_REPAIR_STAGES
        }
        if structural_scopes:
            for scope in ("contract", "plan", "spoken_base"):
                if scope not in structural_scopes:
                    continue
                repair_stage = STRUCTURAL_REPAIR_STAGES[scope]
                repaired = await run_stage(
                    repair_stage,
                    context,
                    config,
                    client,
                    prompts,
                    intermediates,
                    f"{repair_stage}_{attempt + 1}",
                )
                context[{
                    "contract": "clinical_contract",
                    "plan": "encounter_plan",
                    "spoken_base": "spoken_base",
                }[scope]] = repaired

            earliest_scope = min(
                ("contract", "plan", "spoken_base"),
                key=lambda scope: ("contract", "plan", "spoken_base").index(scope)
                if scope in structural_scopes else 99,
            )
            if earliest_scope in {"contract", "plan"} and "plan" not in structural_scopes:
                context["encounter_plan"] = await run_stage(
                    "stage2_encounter_plan", context, config, client, prompts,
                    intermediates, f"stage2_regenerated_{attempt + 1}",
                )
            if earliest_scope in {"contract", "plan", "spoken_base"} and "spoken_base" not in structural_scopes:
                context["spoken_base"] = await run_stage(
                    "stage3_spoken_base", context, config, client, prompts,
                    intermediates, f"stage3_regenerated_{attempt + 1}",
                )
            context["disfluency_plan"] = await run_stage(
                "stage4_disfluency_plan", context, config, client, prompts,
                intermediates, f"stage4_regenerated_{attempt + 1}",
            )
            context["repair_targets"] = []
            context["dialogue"] = await run_stage(
                "stage5_surface_generation", context, config, client, prompts,
                intermediates, f"stage5_regenerated_{attempt + 1}",
            )
            continue
        context["dialogue"] = await run_stage(
            "stage5_surface_generation",
            context, config, client, prompts, intermediates,
            f"stage5_repair_{attempt + 1}",
        )

    generated = context["dialogue"]
    generated_meta = generated.get("meta") if isinstance(generated.get("meta"), dict) else {}
    final_meta = dict(generated_meta)
    final_meta.update(context["record"].get("meta", {}))
    result = {
        "dialogue_id": generated.get("dialogue_id", dialogue_id),
        "source": context["source"],
        "meta": final_meta,
        "dialogue": generated.get("dialogue", []),
        "validation_verdict": validation.get("verdict", "unknown"),
    }
    if validation.get("verdict") != "pass":
        result["validation_failed"] = True
    if config.save_intermediates:
        save_intermediates(dialogue_id, intermediates, config.intermediates_dir)
    return result


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.warning(f"Skipping invalid JSON at {path}:{line_number}: {exc}")
            continue
        if isinstance(item, dict):
            rows.append(item)
        else:
            logger.warning(f"Skipping non-object JSON at {path}:{line_number}")
    return rows


def entry_id(item: Dict[str, Any]) -> Optional[str]:
    value = item.get("dialogue_id") or item.get("id") or item.get("script_id")
    return str(value) if value is not None else None


def deduplicate_entries(entries: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep the first occurrence of each explicit dialogue ID before scheduling."""
    seen: Set[str] = set()
    unique: List[Dict[str, Any]] = []
    for item in entries:
        identifier = entry_id(item)
        if identifier is not None and identifier in seen:
            logger.warning(f"Skipping duplicate dialogue_id={identifier}")
            continue
        if identifier is not None:
            seen.add(identifier)
        unique.append(item)
    return unique


def existing_ids(path: Path) -> Set[str]:
    if not path.exists():
        return set()
    return {identifier for row in read_jsonl(path) if (identifier := entry_id(row))}


async def async_main(
    entries: List[Dict[str, Any]],
    config: PipelineConfig,
    output: Path,
    concurrency: int,
    supplement: bool,
    prompt_path: Path,
) -> None:
    invalid_path = output.with_name(output.stem + "_invalid.jsonl")
    mode = "a" if supplement else "w"
    semaphore = asyncio.Semaphore(max(1, concurrency))
    write_lock = asyncio.Lock()
    kept = 0
    failed = 0
    with output.open(mode, encoding="utf-8") as good, invalid_path.open(
        mode, encoding="utf-8"
    ) as bad:

        async def process_one(item: Dict[str, Any]) -> None:
            nonlocal kept, failed
            async with semaphore:
                try:
                    result = await async_run_pipeline(item, config, prompt_path)
                    row = {key: result[key] for key in ("dialogue_id", "source", "meta", "dialogue")}
                    async with write_lock:
                        target = bad if result.get("validation_failed") else good
                        target.write(json.dumps(row, ensure_ascii=False) + "\n")
                        target.flush()
                        if result.get("validation_failed"):
                            failed += 1
                        else:
                            kept += 1
                except Exception as exc:
                    async with write_lock:
                        failed += 1
                    logger.error(f"[{entry_id(item) or 'unknown'}] Pipeline failed: {exc}")

        tasks = [process_one(item) for item in entries]
        for task in tqdm(
            asyncio.as_completed(tasks), total=len(tasks), desc="Converting", unit="dialogue"
        ):
            await task
    tqdm.write(
        f"Done. kept={kept}/{len(entries)}, failed={failed}/{len(entries)}, "
        f"output={output}, invalid={invalid_path}"
    )


def parse_selected_ids(value: str) -> Set[int]:
    return {int(part.strip()) for part in value.split(",") if part.strip()}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="convert_v2 planner–generator medical dialogue conversion pipeline"
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--provider", choices=["deepseek", "qwen", "gemini"], default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--no-thinking", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=65536)
    parser.add_argument("--max-retry", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--sel-ids", type=parse_selected_ids, default=None)
    parser.add_argument("--save-intermediates", action="store_true")
    parser.add_argument("--planner-model", default=None)
    parser.add_argument("--writer-model", default=None)
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--stage-effort", nargs="*", default=None)
    parser.add_argument("--stage-temperature", nargs="*", default=None)
    parser.add_argument("--supplement", action="store_true")
    parser.add_argument("--prompt", default=None, help="Path to v5_complete.md")
    args = parser.parse_args()

    source = Path(args.input)
    output = Path(args.output)
    prompt_path = resolve_prompt_path(args.prompt)
    if not source.exists():
        logger.error(f"Input file not found: {source}")
        sys.exit(1)
    if not prompt_path.exists():
        logger.error(f"Prompt book not found: {prompt_path}")
        sys.exit(1)

    output.parent.mkdir(parents=True, exist_ok=True)
    entries = read_jsonl(source)
    if args.sel_ids is not None:
        entries = [
            row
            for row in entries
            if (identifier := entry_id(row)) is not None
            and identifier.isdigit()
            and int(identifier) in args.sel_ids
        ]
    entries = deduplicate_entries(entries)
    if args.supplement:
        completed = existing_ids(output)
        entries = [row for row in entries if entry_id(row) not in completed]
    if not entries:
        logger.warning("No records to process")
        return

    config = create_config_from_args(args)
    asyncio.run(
        async_main(entries, config, output, args.concurrency, args.supplement, prompt_path)
    )


if __name__ == "__main__":
    main()
