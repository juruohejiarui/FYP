#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Convert cleaned medical dialogues into a more natural offline conversation style
using DeepSeek-V4-Flash (thinking mode).

Input schema (one JSON object per line):
{
  "dialogue_id": 1283,
  "source": "ReMeDi-base",
  "meta": {"sex": "女", "age": 31},
  "dialogue": [
    {"speaker": "患者", "text": "..."},
    {"speaker": "医生", "text": "..."}
  ]
}

Output schema (one JSON object per line, same fields):
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
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List
from tqdm import tqdm
from openai import OpenAI


DEFAULT_SYSPROMPT_FILE = Path(__file__).parent / "convert_sysprompt.md"
DEFAULT_USERPROMPT_FILE = Path(__file__).parent / "convert_userprompt.md"


def load_system_prompt(filepath: Path = DEFAULT_SYSPROMPT_FILE) -> str:
    """Load system prompt from markdown file, removing markdown header markers."""
    if not filepath.exists():
        raise FileNotFoundError(f"System prompt file not found: {filepath}")
    
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Remove markdown headers and keep the content
    lines = content.splitlines()
    cleaned_lines = []
    for line in lines:
        # Skip markdown headers (lines starting with #)
        if line.strip().startswith("#"):
            continue
        cleaned_lines.append(line)
    
    return "\n".join(cleaned_lines).strip()


def load_user_prompt(filepath: Path = DEFAULT_USERPROMPT_FILE) -> str:
    """Load full user prompt from markdown file, including few-shot examples."""
    if not filepath.exists():
        raise FileNotFoundError(f"User prompt file not found: {filepath}")
    
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Remove top-level markdown headers but keep everything else
    lines = content.splitlines()
    cleaned_lines = []
    for line in lines:
        # Skip only top-level headers (# not ##)
        if line.strip().startswith("# ") and not line.strip().startswith("# # "):
            continue
        cleaned_lines.append(line)
    
    return "\n".join(cleaned_lines).strip()


SYSTEM_PROMPT = load_system_prompt()
USER_PROMPT_TEMPLATE = load_user_prompt()



def build_messages(record: Dict[str, Any]) -> List[Dict[str, str]]:
    """Build messages: system prompt + full user prompt (with few shots) + actual record."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # User message: template prompt (with few shots) + the actual record to convert
    user_content = USER_PROMPT_TEMPLATE + "\n\n## 要转换的医患对话\n\n```json\n" + json.dumps(record, ensure_ascii=False) + "\n```"
    messages.append({"role": "user", "content": user_content})
    
    return messages


def extract_json_object(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    # Fast path.
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # Fallback: extract the first JSON object.
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("No JSON object found in model output")
    obj = json.loads(m.group(0))
    if not isinstance(obj, dict):
        raise ValueError("Model output is not a JSON object")
    return obj


def normalize_output(obj: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "dialogue_id": obj.get("dialogue_id", fallback.get("dialogue_id")),
        "source": obj.get("source", fallback.get("source", "")),
        "meta": obj.get("meta", fallback.get("meta", {})),
        "dialogue": obj.get("dialogue", fallback.get("dialogue", [])),
    }

    # Light validation/cleanup.
    cleaned_dialogue = []
    for turn in out["dialogue"] if isinstance(out["dialogue"], list) else []:
        if not isinstance(turn, dict):
            continue
        speaker = str(turn.get("speaker", "")).strip()
        text = str(turn.get("text", "")).strip()
        if speaker and text:
            cleaned_dialogue.append({"speaker": speaker, "text": text})
    out["dialogue"] = cleaned_dialogue
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert cleaned medical dialogues with DeepSeek-V4-Flash.")
    parser.add_argument("--input", required=True, help="Path to scripts-clean.jsonl")
    parser.add_argument("--output", required=True, help="Path to script-convert.jsonl")
    parser.add_argument("--model", default="deepseek-v4-pro", help="DeepSeek model name")
    parser.add_argument("--base-url", default="https://api.deepseek.com", help="DeepSeek base URL")
    parser.add_argument("--api-key", default=os.getenv("DEEPSEEK_API_KEY", ""), help="DeepSeek API key")
    parser.add_argument("--thinking", action="store_true", help="Enable thinking mode (default recommended).")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--temperature", type=float, default=0.4)
    parser.add_argument("--max-retry", type=int, default=3, help="Max retries for each record conversion")
    args = parser.parse_args()

    if not args.api_key:
        raise RuntimeError("Missing API key. Set DEEPSEEK_API_KEY or pass --api-key.")

    client = OpenAI(api_key=args.api_key, base_url=args.base_url)

    in_path = Path(args.input)
    out_path = Path(args.output)

    kept = 0
    failed = 0

    with in_path.open("r", encoding="utf-8") as fin, out_path.open("w", encoding="utf-8") as fout:
        for lineno, line in tqdm(enumerate(fin, 1)):
            line = line.strip()
            if not line:
                continue

            record = json.loads(line)
            if not isinstance(record, dict):
                failed += 1
                continue

            messages = build_messages(record)

            kwargs = dict(
                model=args.model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=args.temperature,
                max_tokens=args.max_tokens,
            )
            if args.thinking:
                kwargs["reasoning_effort"] = "high"
                kwargs["extra_body"]={"thinking": {"type": "enabled"}}

            # ----- 重试循环 -----
            success = False
            for attempt in range(1, args.max_retry + 1):
                normalized : Dict[str, any] = {}
                try:
                    resp = client.chat.completions.create(**kwargs)
                    content = resp.choices[0].message.content or ""
                    obj = extract_json_object(content)
                    normalized = normalize_output(obj, record)
                    fout.write(json.dumps(normalized, ensure_ascii=False) + "\n")
                    kept += 1
                    success = True
                    break  # 成功即退出重试
                except Exception as e:
                    print(f"[WARN] line {lineno} attempt {attempt}/{args.max_retry} failed: {e}")
                    print(f"Raw output: {content}")
                    if attempt < args.max_retry:
                        # 简单指数退避，避免频繁请求
                        wait = 2 ** (attempt - 1)
                        time.sleep(wait)
                    else:
                        # 所有重试耗尽，记录失败
                        failed += 1
                        # 可选：将原始记录写入输出作为占位，避免丢失数据
                        # fout.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"Done. kept={kept}, failed={failed}, output={out_path}")


if __name__ == "__main__":
    main()
