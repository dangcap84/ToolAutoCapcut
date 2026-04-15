from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

DEFAULT_MASK_BG_CACHE_ROOT = Path(
    "C:/Users/Admin/AppData/Local/CapCut/User Data/Cache/mask_background_pack"
)

DEFAULT_MASK_BG_PACK_ROOT = Path(__file__).resolve().parent / "mask_background_pack"
DEFAULT_MASK_BG_PACK_ZIP = Path(__file__).resolve().parent / "mask_background_pack.zip"

_MASK_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}


def _candidate_pack_roots() -> list[Path]:
    roots: list[Path] = [DEFAULT_MASK_BG_PACK_ROOT]

    if getattr(sys, "frozen", False):
        try:
            exe_dir = Path(sys.executable).resolve().parent
            roots.insert(0, exe_dir / "mask_background_pack")
        except Exception:
            pass

    out: list[Path] = []
    seen: set[str] = set()
    for r in roots:
        key = str(r)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _candidate_pack_zips() -> list[Path]:
    zips: list[Path] = [DEFAULT_MASK_BG_PACK_ZIP]

    if getattr(sys, "frozen", False):
        try:
            exe_dir = Path(sys.executable).resolve().parent
            zips.insert(0, exe_dir / "mask_background_pack.zip")
        except Exception:
            pass

        try:
            meipass = Path(getattr(sys, "_MEIPASS", ""))
            if str(meipass):
                zips.insert(0, meipass / "mask_background_pack.zip")
        except Exception:
            pass

    out: list[Path] = []
    seen: set[str] = set()
    for p in zips:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _iter_video_files(root: Path) -> list[Path]:
    if not root.exists() or not root.is_dir():
        return []
    return sorted(
        [
            p
            for p in root.iterdir()
            if p.is_file() and p.suffix.lower() in _MASK_VIDEO_EXTS
        ],
        key=lambda p: p.name.lower(),
    )


def seed_mask_background_cache_from_pack(
    cache_root: Path | None = None,
) -> int:
    if cache_root is None:
        cache_root = DEFAULT_MASK_BG_CACHE_ROOT

    try:
        cache_root.mkdir(parents=True, exist_ok=True)
    except Exception:
        return 0

    copied = 0
    for root in _candidate_pack_roots():
        for src in _iter_video_files(root):
            dst = cache_root / src.name
            if dst.exists() and dst.stat().st_size > 0:
                continue
            try:
                shutil.copy2(src, dst)
                copied += 1
            except Exception:
                continue
    return copied


def seed_mask_background_cache_from_zip(
    zip_path: Path,
    cache_root: Path | None = None,
) -> int:
    if cache_root is None:
        cache_root = DEFAULT_MASK_BG_CACHE_ROOT

    try:
        cache_root.mkdir(parents=True, exist_ok=True)
    except Exception:
        return 0

    if not zip_path.exists() or not zip_path.is_file():
        return 0

    copied = 0
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                raw = info.filename.replace("\\", "/")
                if not raw or raw.endswith("/"):
                    continue
                name = Path(raw).name
                if not name:
                    continue
                if Path(name).suffix.lower() not in _MASK_VIDEO_EXTS:
                    continue

                dst = cache_root / name
                if dst.exists() and dst.stat().st_size > 0:
                    continue

                data = zf.read(info)
                dst.write_bytes(data)
                copied += 1
    except Exception:
        return 0

    return copied


def seed_mask_background_cache(cache_root: Path | None = None) -> int:
    copied = 0
    for z in _candidate_pack_zips():
        copied += seed_mask_background_cache_from_zip(z, cache_root=cache_root)
    copied += seed_mask_background_cache_from_pack(cache_root=cache_root)
    return copied


def load_mask_background_library(cache_root: Path | None = None) -> list[dict[str, Any]]:
    if cache_root is None:
        cache_root = DEFAULT_MASK_BG_CACHE_ROOT

    seed_mask_background_cache(cache_root=cache_root)

    out: list[dict[str, Any]] = []
    for p in _iter_video_files(cache_root):
        out.append(
            {
                "name": p.name,
                "path": str(p).replace("\\", "/"),
            }
        )
    return out
