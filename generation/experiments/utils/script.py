import json
from pathlib import Path
from loguru import logger

def parse(path: Path | str) -> list[dict]:
    entries: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.warning("Skipping invalid JSON at {}:{}: {}".format(path, line_number, exc))
    return entries