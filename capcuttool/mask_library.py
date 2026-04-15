from __future__ import annotations

import os
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any


def _user_home_dir() -> Path:
    env = os.environ
    for key in ("USERPROFILE", "HOME"):
        v = str(env.get(key) or "").strip()
        if v:
            return Path(v)

    drive = str(env.get("HOMEDRIVE") or "").strip()
    hpath = str(env.get("HOMEPATH") or "").strip()
    if drive and hpath:
        return Path(f"{drive}{hpath}")

    return Path.home()


def _default_capcut_cache_root() -> Path:
    return _user_home_dir() / "AppData" / "Local" / "CapCut" / "User Data" / "Cache"


DEFAULT_CAPCUT_CACHE_ROOT = _default_capcut_cache_root()
DEFAULT_MASK_BG_CACHE_ROOT = DEFAULT_CAPCUT_CACHE_ROOT / "mask_background_pack"
DEFAULT_ONLINE_MATERIAL_ROOT = DEFAULT_CAPCUT_CACHE_ROOT / "onlineMaterial"

DEFAULT_MASK_BG_PACK_ROOT = Path(__file__).resolve().parent / "mask_background_pack"
DEFAULT_MASK_BG_PACK_ZIP = Path(__file__).resolve().parent / "mask_background_pack.zip"

_MASK_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}

# 2 background gốc của tool (được user add vào Favorite trong CapCut).
# Khi thấy trong onlineMaterial, ưu tiên show đúng tên dễ đọc thay vì id/hash filename.
_BUILTIN_BG_ALIAS_TO_NAME: dict[str, str] = {
    "daf89cec03e1d2c4cbbd24050a9287fd.mp4": "Background 01",
    "5f7c5949617cf594f28e69e968a64bc8.mp4": "Background 02",
}


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


def _iter_video_files_recursive(root: Path, max_items: int = 2000) -> list[Path]:
    if not root.exists() or not root.is_dir():
        return []

    out: list[Path] = []
    try:
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in _MASK_VIDEO_EXTS:
                continue
            out.append(p)
            if len(out) >= max_items:
                break
    except Exception:
        return []

    out.sort(key=lambda p: p.name.lower())
    return out


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


def _library_from_paths(paths: list[Path], source: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Ưu tiên file mới hơn để user thấy asset vừa tải về trước.
    paths = sorted(paths, key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)

    for p in paths:
        if not p.exists() or not p.is_file():
            continue
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        display_name = p.name
        if source == "onlineMaterial":
            display_name = _BUILTIN_BG_ALIAS_TO_NAME.get(p.name.lower(), p.name)

        out.append(
            {
                "name": display_name,
                "path": str(p).replace("\\", "/"),
                "source": source,
                "raw_name": p.name,
            }
        )

    return out


def load_mask_background_library(cache_root: Path | None = None) -> list[dict[str, Any]]:
    """
    Ưu tiên background từ CapCut cache (onlineMaterial).

    Với case user chỉ muốn đúng 2 background gốc đã đánh dấu Favorite:
    - nếu tìm thấy 2 alias built-in trong onlineMaterial -> chỉ trả về 2 item đó
      và dùng tên dễ đọc (Background 01/02), không hiện id/hash.
    - nếu không đủ alias -> fallback trả toàn bộ onlineMaterial.
    """
    if cache_root is None:
        cache_root = DEFAULT_MASK_BG_CACHE_ROOT

    # vẫn seed pack vào cache để backward-compatible, nhưng KHÔNG đưa vào library mặc định
    seed_mask_background_cache(cache_root=cache_root)

    online_videos = _iter_video_files_recursive(DEFAULT_ONLINE_MATERIAL_ROOT, max_items=4000)
    if not online_videos:
        return []

    by_name = {p.name.lower(): p for p in online_videos}
    preferred: list[Path] = []
    for alias in _BUILTIN_BG_ALIAS_TO_NAME.keys():
        p = by_name.get(alias)
        if p is not None:
            preferred.append(p)

    if preferred:
        return _library_from_paths(preferred, source="onlineMaterial")

    return _library_from_paths(online_videos, source="onlineMaterial")
