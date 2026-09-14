#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""convert_v3 clinical-constraint-to-transcript conversion pipeline.

Compact source turns are visible from meta inference through Spoken Base.
Later stages receive previous line-plan blocks. Structural repair can jump
back to brief / director / plan / spoken_base, then regenerate downstream.
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

from .config import PipelineConfig
from .utils import async_stage_llm_call, load_pipeline_config, save_intermediates


MAX_REPAIR_ATTEMPTS = 2
MISSING = {"", "none", "null", "unknown", "unk", "n/a", "na", "未知"}
STAGES = (
    "stage0_meta_inference",
    "stage1_clinical_brief",
    "stage2_encounter_director",
    "stage3_spoken_performance_plan",
    "stage4_spoken_base",
    "stage5_disfluency_plan",
    "stage6_surface_generation",
    "stage7_clinical_naturalness_judge",
)
REPAIR_STAGE = "stage6_surface_repair"
STRUCTURAL_REPAIR_STAGES = {
    "brief": "stage1_clinical_brief_repair",
    "director": "stage2_encounter_director_repair",
    "plan": "stage3_spoken_performance_plan_repair",
    "spoken_base": "stage4_spoken_base_repair",
}
SCOPE_CONTEXT_KEY = {
    "brief": "clinical_brief",
    "director": "encounter_director",
    "plan": "spoken_performance_plan",
    "spoken_base": "spoken_base",
}
CASCADE_ORDER = ("brief", "director", "plan", "spoken_base")
SOURCE_STAGES = {
    "stage0_meta_inference",
    "stage1_clinical_brief",
    "stage2_encounter_director",
    "stage3_spoken_performance_plan",
    "stage4_spoken_base",
    "stage1_clinical_brief_repair",
    "stage2_encounter_director_repair",
    "stage3_spoken_performance_plan_repair",
    "stage4_spoken_base_repair",
}
SYSTEM = {
    "stage0_meta_inference": "Infer missing metadata only. Return one JSON object.",
    "stage1_clinical_brief": "Extract clinical constraints only. Return one [CLINICAL_BRIEF] block.",
    "stage2_encounter_director": "Direct a new offline encounter from constraints. Return one [ENCOUNTER_DIRECTOR] block.",
    "stage3_spoken_performance_plan": "Plan spoken interactions. Return one [SPOKEN_PERFORMANCE_PLAN] block.",
    "stage4_spoken_base": "Write a fluent spoken base from the plan. Return one [SPOKEN_BASE] block.",
    "stage5_disfluency_plan": "Plan local disfluency only. Return one [DISFLUENCY_PLAN] block.",
    "stage6_surface_generation": "Realize the disfluency plan as a Chinese outpatient transcript. Return one JSON object.",
    "stage7_clinical_naturalness_judge": "Audit clinical constraints and transcript naturalness. Return one JSON object.",
    "stage1_clinical_brief_repair": "Repair the clinical brief only. Return one [CLINICAL_BRIEF] block.",
    "stage2_encounter_director_repair": "Repair the encounter director only. Return one [ENCOUNTER_DIRECTOR] block.",
    "stage3_spoken_performance_plan_repair": "Repair the spoken performance plan only. Return one [SPOKEN_PERFORMANCE_PLAN] block.",
    "stage4_spoken_base_repair": "Repair the spoken base only. Return one [SPOKEN_BASE] block.",
}
_SPEAKER_ABBREV = {
    "患者": "患",
    "医生": "医",
    "陪诊者": "陪",
}


def load_prompt_book(path: Path) -> Dict[str, str]:
    """Read the one-file prompt book; keep the preamble before the first stage."""
    text = path.read_text(encoding="utf-8")
    parts = text.split("<!-- STAGE: ")
    prompts: Dict[str, str] = {"_preamble": parts[0].strip()}
    for chunk in parts[1:]:
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
        package_dir / "prompts" / "v6_complete.md",
        package_dir / "v6_complete.md",
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


def _fmt_meta(value: Any) -> str:
    if value is None or is_missing(value):
        return "null"
    return str(value)


def compact_source(record: Dict[str, Any]) -> str:
    """Render identity plus original turns as compact lines, not JSON."""
    meta = record.get("meta") or {}
    dialogue_id = record.get("dialogue_id") or record.get("id") or ""
    lines = [
        "[SOURCE]",
        f"id={dialogue_id}",
        f"source={record.get('source') or ''}",
        (
            f"meta: sex={_fmt_meta(meta.get('sex'))} | "
            f"age={_fmt_meta(meta.get('age'))} | "
            f"language={_fmt_meta(meta.get('language'))}"
        ),
        "[TURNS]",
    ]
    for turn in record.get("dialogue") or []:
        text = re.sub(r"\s+", " ", str(turn.get("text") or "")).strip()
        if not text:
            continue
        speaker = str(turn.get("speaker") or "").strip()
        speaker = _SPEAKER_ABBREV.get(speaker, speaker)
        if not speaker:
            continue
        lines.append(f"{speaker} | {text}")
    lines.append("[/TURNS]")
    lines.append("[/SOURCE]")
    return "\n".join(lines)


def _join_blocks(*blocks: str) -> str:
    return "\n\n".join(block.strip() for block in blocks if block and block.strip())


def _source_block(context: Dict[str, Any]) -> str:
    return "## Source (reference)\n" + compact_source(context["record"])


def _with_preamble(prompts: Dict[str, str], body: str) -> str:
    preamble = prompts.get("_preamble") or ""
    if preamble:
        return preamble + "\n\n" + body
    return body


def stage_user_content(
    stage: str,
    context: Dict[str, Any],
    prompt_body: str,
) -> str:
    """Assemble the user message: stage prompt plus previous outputs as raw text."""
    source = ""
    if stage in SOURCE_STAGES:
        source = "\n\n" + _source_block(context)

    if stage in {"stage0_meta_inference", "stage1_clinical_brief"}:
        return prompt_body + source

    if stage == "stage2_encounter_director":
        prior = "## Previous stage output\n" + context["clinical_brief"]
        return prompt_body + "\n\n" + prior + source

    if stage == "stage3_spoken_performance_plan":
        prior = "## Previous stage outputs\n" + _join_blocks(
            context["clinical_brief"],
            context["encounter_director"],
        )
        return prompt_body + "\n\n" + prior + source

    if stage == "stage4_spoken_base":
        prior = "## Previous stage outputs\n" + _join_blocks(
            context["clinical_brief"],
            context["encounter_director"],
            context["spoken_performance_plan"],
        )
        return prompt_body + "\n\n" + prior + source

    if stage == "stage5_disfluency_plan":
        prior = "## Previous stage outputs\n" + _join_blocks(
            context["clinical_brief"],
            context["encounter_director"],
            context["spoken_performance_plan"],
            context["spoken_base"],
        )
        return prompt_body + "\n\n" + prior

    if stage in STRUCTURAL_REPAIR_STAGES.values():
        repair_scope = next(
            scope for scope, repair_stage in STRUCTURAL_REPAIR_STAGES.items()
            if repair_stage == stage
        )
        previous_key = SCOPE_CONTEXT_KEY[repair_scope]
        prior_blocks = []
        if repair_scope in {"director", "plan", "spoken_base"}:
            prior_blocks.append(context["clinical_brief"])
        if repair_scope in {"plan", "spoken_base"}:
            prior_blocks.append(context["encounter_director"])
        if repair_scope == "spoken_base":
            prior_blocks.append(context["spoken_performance_plan"])
        targets = [
            target for target in context["repair_targets"]
            if target.get("scope") == repair_scope
        ]
        extra_source = source if stage in SOURCE_STAGES else ""
        return (
            prompt_body
            + "\n\n## Previous stage outputs\n"
            + _join_blocks(*prior_blocks)
            + "\n\n## Previous target block\n"
            + context[previous_key]
            + "\n\n## Structural repair targets\n```json\n"
            + json.dumps(targets, ensure_ascii=False)
            + "\n```"
            + extra_source
        )

    identity = (
        "## Output identity JSON\n```json\n"
        + json.dumps(output_identity(context), ensure_ascii=False)
        + "\n```"
    )
    plans = "## Previous stage outputs\n" + _join_blocks(
        context["clinical_brief"],
        context["encounter_director"],
        context["spoken_performance_plan"],
        context["spoken_base"],
        context["disfluency_plan"],
    )
    if stage == "stage6_surface_generation":
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
    prompts: Dict[str, str],
    intermediates: Dict[str, Any],
    saved_name: str,
) -> Any:
    is_repair = stage == "stage6_surface_generation" and context.get("repair_targets")
    prompt_key = REPAIR_STAGE if is_repair else stage
    llm_stage = REPAIR_STAGE if is_repair else stage
    prompt_body = _with_preamble(prompts, prompts[prompt_key])
    user_content = stage_user_content(stage, context, prompt_body)
    tqdm.write(f"[{context['dialogue_id']}] {stage}")
    result = await async_stage_llm_call(
        llm_stage,
        user_content,
        system_prompt=SYSTEM[stage if not is_repair else "stage6_surface_generation"],
        config=config,
    )
    intermediates[saved_name] = result
    return result


async def async_run_pipeline(
    record: Dict[str, Any],
    config: PipelineConfig,
    prompt_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Convert one source record through convert_v3 stages."""
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

    if any(missing_flags):
        inferred = await run_stage(
            "stage0_meta_inference",
            context, config, prompts, intermediates,
            "stage0_meta_inference",
        )
        context["record"]["meta"] = merge_meta(meta_base, inferred, missing_flags)

    context["clinical_brief"] = await run_stage(
        "stage1_clinical_brief",
        context, config, prompts, intermediates,
        "stage1_clinical_brief",
    )
    context["encounter_director"] = await run_stage(
        "stage2_encounter_director",
        context, config, prompts, intermediates,
        "stage2_encounter_director",
    )
    context["spoken_performance_plan"] = await run_stage(
        "stage3_spoken_performance_plan",
        context, config, prompts, intermediates,
        "stage3_spoken_performance_plan",
    )
    context["spoken_base"] = await run_stage(
        "stage4_spoken_base",
        context, config, prompts, intermediates,
        "stage4_spoken_base",
    )
    context["disfluency_plan"] = await run_stage(
        "stage5_disfluency_plan",
        context, config, prompts, intermediates,
        "stage5_disfluency_plan",
    )
    context["dialogue"] = await run_stage(
        "stage6_surface_generation",
        context, config, prompts, intermediates,
        "stage6_initial",
    )

    validation: Dict[str, Any] = {"verdict": "repair", "repair_targets": []}
    for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
        validation = await run_stage(
            "stage7_clinical_naturalness_judge",
            context, config, prompts, intermediates,
            f"stage7_attempt_{attempt + 1}",
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
            for scope in CASCADE_ORDER:
                if scope not in structural_scopes:
                    continue
                repair_stage = STRUCTURAL_REPAIR_STAGES[scope]
                repaired = await run_stage(
                    repair_stage,
                    context, config, prompts, intermediates,
                    f"{repair_stage}_{attempt + 1}",
                )
                context[SCOPE_CONTEXT_KEY[scope]] = repaired

            earliest_scope = min(
                CASCADE_ORDER,
                key=lambda scope: CASCADE_ORDER.index(scope)
                if scope in structural_scopes else 99,
            )
            if earliest_scope == "brief" and "director" not in structural_scopes:
                context["encounter_director"] = await run_stage(
                    "stage2_encounter_director", context, config, prompts,
                    intermediates, f"stage2_regenerated_{attempt + 1}",
                )
            if earliest_scope in {"brief", "director"} and "plan" not in structural_scopes:
                context["spoken_performance_plan"] = await run_stage(
                    "stage3_spoken_performance_plan", context, config, prompts,
                    intermediates, f"stage3_regenerated_{attempt + 1}",
                )
            if (
                earliest_scope in {"brief", "director", "plan"}
                and "spoken_base" not in structural_scopes
            ):
                context["spoken_base"] = await run_stage(
                    "stage4_spoken_base", context, config, prompts,
                    intermediates, f"stage4_regenerated_{attempt + 1}",
                )
            context["disfluency_plan"] = await run_stage(
                "stage5_disfluency_plan", context, config, prompts,
                intermediates, f"stage5_regenerated_{attempt + 1}",
            )
            context["repair_targets"] = []
            context["dialogue"] = await run_stage(
                "stage6_surface_generation", context, config, prompts,
                intermediates, f"stage6_regenerated_{attempt + 1}",
            )
            continue
        context["dialogue"] = await run_stage(
            "stage6_surface_generation",
            context, config, prompts, intermediates,
            f"stage6_repair_{attempt + 1}",
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
    supplement: bool,
    prompt_path: Path,
) -> None:
    invalid_path = output.with_name(output.stem + "_invalid.jsonl")
    mode = "a" if supplement else "w"
    semaphore = asyncio.Semaphore(max(1, config.concurrency))
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
                    row = {
                        key: result[key]
                        for key in ("dialogue_id", "source", "meta", "dialogue")
                    }
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
    parser = argparse.ArgumentParser(description="convert_v3 medical dialogue conversion pipeline")
    parser.add_argument("--config", required=True, help="Path to per-stage LLM JSON config")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sel-ids", type=parse_selected_ids, default=None)
    parser.add_argument("--supplement", action="store_true")
    parser.add_argument("--prompt", default=None, help="prompts/v6_complete.md")
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

    try:
        config = load_pipeline_config(args.config)
    except (OSError, ValueError, RuntimeError) as exc:
        logger.error(f"Failed to load config: {exc}")
        sys.exit(1)
    if config.save_intermediates and config.intermediates_dir is None:
        config.intermediates_dir = output.parent / "intermediates"

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

    asyncio.run(async_main(entries, config, output, args.supplement, prompt_path))


if __name__ == "__main__":
    main()
