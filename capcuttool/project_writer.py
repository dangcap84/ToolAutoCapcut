from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any


def utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def backup_file(path: Path, suffix: str | None = None) -> Path:
    ts = utc_ts()
    stem = path.stem
    ext = path.suffix
    tail = f"_{suffix}" if suffix else ""
    backup = path.with_name(f"{stem}_backup_{ts}{tail}{ext}")
    backup.write_bytes(path.read_bytes())
    return backup


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)
