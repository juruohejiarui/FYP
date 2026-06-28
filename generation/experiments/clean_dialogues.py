#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Clean raw medical dialogue JSONL into a compact JSONL schema.

Input example (one JSON object per line):
{
  "dialogue_id": 1283,
  "source": "ReMeDi-base",
  "patient_profile": {"sex": "女", "age": "31"},
  "tts_segments": [
    {"speaker": "患者", "text": "..."},
    {"speaker": "医生", "text": "..."}
  ],
  ...
}

Output schema (one JSON object per line):
{
  "dialogue_id": 1283,
  "source": "ReMeDi-base",
  "meta": {"sex": "女", "age": 31},
  "dialogue": [
    {"speaker": "患者", "text": "..."},
    {"speaker": "医生", "text": "..."}
  ]
}
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def safe_int(x: Any) -> Optional[int]:
    if x is None:
        return None
    try:
        if isinstance(x, bool):
            return None
        return int(str(x).strip())
    except Exception:
        return None


def normalize_turn(turn: Dict[str, Any]) -> Optional[Dict[str, str]]:
    text = (turn.get("text") or "").strip()
    if not text:
        return None

    speaker = (turn.get("speaker") or turn.get("role") or turn.get("voice_role") or "").strip()
    # Map common voice roles to readable speakers.
    if speaker == "patient_voice":
        speaker = "患者"
    elif speaker == "doctor_voice":
        speaker = "医生"

    # If speaker is still unknown, keep it explicit.
    if not speaker:
        speaker = "未知"

    return {"speaker": speaker, "text": text}


def extract_dialogue(item: Dict[str, Any]) -> List[Dict[str, str]]:
    # Primary source in your examples.
    segs = item.get("tts_segments") or []
    turns: List[Dict[str, str]] = []

    if isinstance(segs, list) and segs:
        for seg in segs:
            if not isinstance(seg, dict):
                continue
            norm = normalize_turn(seg)
            if norm:
                turns.append(norm)
        if turns:
            return turns

    # Fallback: some datasets may already have dialogue/turns fields.
    for key in ("dialogue", "turns", "conversation", "messages"):
        value = item.get(key)
        if isinstance(value, list) and value:
            for seg in value:
                if isinstance(seg, dict):
                    norm = normalize_turn(seg)
                    if norm:
                        turns.append(norm)
                elif isinstance(seg, (list, tuple)) and len(seg) >= 2:
                    speaker = str(seg[0]).strip() or "未知"
                    text = str(seg[1]).strip()
                    if text:
                        turns.append({"speaker": speaker, "text": text})
            if turns:
                return turns

    return turns


def clean_item(item: Dict[str, Any]) -> Dict[str, Any]:
    patient_profile = item.get("patient_profile") or {}
    meta = {
        "sex": patient_profile.get("sex"),
        "age": safe_int(patient_profile.get("age")),
    }

    out = {
        "dialogue_id": item.get("dialogue_id"),
        "source": item.get("source", ""),
        "meta": meta,
        "dialogue": extract_dialogue(item),
    }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean raw medical dialogue JSONL.")
    parser.add_argument("--input", required=True, help="Path to raw scripts.jsonl")
    parser.add_argument("--output", required=True, help="Path to scripts-clean.jsonl")
    args = parser.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)

    kept = 0
    skipped = 0

    with in_path.open("r", encoding="utf-8") as fin, out_path.open("w", encoding="utf-8") as fout:
        for lineno, line in enumerate(fin, 1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if not isinstance(item, dict):
                    skipped += 1
                    continue
                cleaned = clean_item(item)
                # Skip empty dialogues.
                if not cleaned["dialogue"]:
                    skipped += 1
                    continue
                fout.write(json.dumps(cleaned, ensure_ascii=False) + "\n")
                kept += 1
            except Exception as e:
                skipped += 1
                print(f"[WARN] line {lineno} skipped: {e}")

    print(f"Done. kept={kept}, skipped={skipped}, output={out_path}")


if __name__ == "__main__":
    main()
