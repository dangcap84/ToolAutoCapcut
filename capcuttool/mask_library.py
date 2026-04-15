from __future__ import annotations

import os
import shutil
import sys
import zipfile
import json
import re
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
DEFAULT_CAPCUT_USER_DATA_ROOT = _user_home_dir() / "AppData" / "Local" / "CapCut" / "User Data"
DEFAULT_MASK_BG_CACHE_ROOT = DEFAULT_CAPCUT_CACHE_ROOT / "mask_background_pack"
DEFAULT_ONLINE_MATERIAL_ROOT = DEFAULT_CAPCUT_CACHE_ROOT / "onlineMaterial"

DEFAULT_MASK_BG_PACK_ROOT = Path(__file__).resolve().parent / "mask_background_pack"
DEFAULT_MASK_BG_PACK_ZIP = Path(__file__).resolve().parent / "mask_background_pack.zip"
DEFAULT_CAPCUT_PROJECTS_ROOT = DEFAULT_CAPCUT_USER_DATA_ROOT / "Projects" / "com.lveditor.draft"

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
        out.append(
            {
                "name": p.name,
                "path": str(p).replace("\\", "/"),
                "source": source,
                "raw_name": p.name,
            }
        )

    return out


def _safe_load_json(path: Path) -> dict[str, Any] | list[Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _iter_capcut_project_dirs(root: Path = DEFAULT_CAPCUT_PROJECTS_ROOT) -> list[Path]:
    if not root.exists() or not root.is_dir():
        return []

    out: list[Path] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        name = child.name.lower()
        if name.startswith(".") or name == ".recycle_bin":
            continue
        out.append(child)

    # project vừa chỉnh gần nhất lên trước
    out.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return out


def _extract_favorite_media_ids_from_key_value(data: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for _, v in data.items():
        if not isinstance(v, dict):
            continue

        material_id = str(v.get("materialId") or "").strip()
        if not material_id:
            continue

        # chỉ lấy media background/video, bỏ audio/text favorite
        material_category = str(v.get("materialCategory") or "").strip().lower()
        if material_category and material_category != "media":
            continue

        is_favorite = bool(v.get("is_favorite") is True)
        third = str(v.get("materialThirdcategory") or "").strip().lower()
        third_id = str(v.get("materialThirdcategoryId") or "").strip()

        # CapCut dùng nhiều marker favorite khác nhau theo version/account:
        # - materialThirdcategoryId: 100000 hoặc -100
        # - materialThirdcategory text có thể bị mojibake nên chỉ fuzzy theo từ khóa
        third_hint = third.replace("_", " ").replace("-", " ")
        is_favorite_bucket = (
            third_id in {"100000", "-100"}
            or ("yêu thích" in third_hint)
            or ("yeu thich" in third_hint)
            or ("favorite" in third_hint)
            or ("fav" in third_hint)
        )

        if not (is_favorite or is_favorite_bucket):
            continue

        out[material_id] = str(v.get("materialName") or material_id)
    return out


def _extract_favorite_material_ids_from_text_blob(text: str) -> set[str]:
    out: set[str] = set()

    patterns = [
        # JSON thường
        r'"materialId"\s*:\s*"([0-9A-Za-z_-]{8,})"[^\n\r]{0,240}?"is_favorite"\s*:\s*true',
        r'"is_favorite"\s*:\s*true[^\n\r]{0,240}?"materialId"\s*:\s*"([0-9A-Za-z_-]{8,})"',
        # JSON bị escape trong LevelDB value
        r'\\"materialId\\"\s*:\s*\\"([0-9A-Za-z_-]{8,})\\"[^\n\r]{0,260}?\\"is_favorite\\"\s*:\s*true',
        r'\\"is_favorite\\"\s*:\s*true[^\n\r]{0,260}?\\"materialId\\"\s*:\s*\\"([0-9A-Za-z_-]{8,})\\"',
        # Favorite bucket marker
        r'"materialId"\s*:\s*"([0-9A-Za-z_-]{8,})"[^\n\r]{0,260}?"materialThirdcategoryId"\s*:\s*"(?:100000|-100)"',
        r'"materialThirdcategoryId"\s*:\s*"(?:100000|-100)"[^\n\r]{0,260}?"materialId"\s*:\s*"([0-9A-Za-z_-]{8,})"',
    ]

    for pat in patterns:
        try:
            for m in re.finditer(pat, text, flags=re.IGNORECASE):
                mid = (m.group(1) or "").strip()
                if mid:
                    out.add(mid)
        except Exception:
            continue

    return out


def _read_text_best_effort(path: Path, max_bytes: int = 8 * 1024 * 1024) -> str:
    try:
        data = path.read_bytes()
        if len(data) > max_bytes:
            data = data[:max_bytes]
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _collect_global_favorite_material_ids(user_data_root: Path = DEFAULT_CAPCUT_USER_DATA_ROOT) -> set[str]:
    """
    Thu favorite từ kho dữ liệu chung của CapCut (không phụ thuộc project cụ thể).
    """
    roots = [
        user_data_root / "Cache" / "onlineMaterial",
        user_data_root / "Cache" / "ressdk_db",
        user_data_root / "CEF" / "Local Storage" / "leveldb",
        user_data_root / "CEF" / "IndexedDB",
        user_data_root / "Projects" / "com.lveditor.draft",
    ]

    file_suffixes = {".json", ".log", ".txt", ".ldb", ".sst", ".bin"}
    out: set[str] = set()

    for root in roots:
        if not root.exists() or not root.is_dir():
            continue

        seen = 0
        try:
            for p in root.rglob("*"):
                if not p.is_file():
                    continue
                if p.suffix.lower() not in file_suffixes:
                    continue

                blob = _read_text_best_effort(p)
                if not blob:
                    continue

                mids = _extract_favorite_material_ids_from_text_blob(blob)
                if mids:
                    out.update(mids)

                seen += 1
                if seen >= 1200:
                    break
        except Exception:
            continue

    return out


def _collect_favorite_background_items_from_projects(projects_root: Path = DEFAULT_CAPCUT_PROJECTS_ROOT, global_favorite_ids: set[str] | None = None) -> list[dict[str, Any]]:
    """
    Tìm đúng thuộc tính favorite trong CapCut project data rồi map ra file background video thật.

    Luồng map:
    - key_value.json -> lấy materialId có is_favorite=true hoặc thuộc bucket "Yêu thích".
    - draft_content.json -> tìm material/video có material_id đó và path nằm trong onlineMaterial.
    """
    project_dirs = _iter_capcut_project_dirs(projects_root)
    if not project_dirs:
        return []

    seen_path: set[str] = set()
    out: list[dict[str, Any]] = []

    global_ids = set(global_favorite_ids or set())

    for proj in project_dirs:
        key_value_path = proj / "key_value.json"
        draft_content_path = proj / "draft_content.json"
        if not key_value_path.exists() or not draft_content_path.exists():
            continue

        key_data = _safe_load_json(key_value_path)
        if not isinstance(key_data, dict):
            continue

        fav_ids = _extract_favorite_media_ids_from_key_value(key_data)
        merged_fav_ids: set[str] = set(fav_ids.keys()) | global_ids
        if not merged_fav_ids:
            continue

        draft_data = _safe_load_json(draft_content_path)
        if not isinstance(draft_data, dict):
            continue

        materials = draft_data.get("materials")
        if not isinstance(materials, dict):
            continue

        videos = materials.get("videos")
        if not isinstance(videos, list):
            continue

        for item in videos:
            if not isinstance(item, dict):
                continue

            material_id = str(item.get("material_id") or "").strip()
            if not material_id or material_id not in merged_fav_ids:
                continue

            raw_path = str(item.get("path") or item.get("media_path") or "").strip()
            if not raw_path:
                continue

            if "onlinematerial" not in raw_path.lower():
                continue

            path_obj = Path(raw_path)
            if path_obj.suffix.lower() not in _MASK_VIDEO_EXTS:
                continue

            path_norm = str(path_obj).replace("\\", "/")
            key = path_norm.lower()
            if key in seen_path:
                continue
            seen_path.add(key)

            display_name = str(item.get("material_name") or fav_ids.get(material_id) or path_obj.name)
            source = "favorite"
            if material_id in global_ids and material_id not in fav_ids:
                source = "favorite-global"
            out.append(
                {
                    "name": path_obj.name,
                    "display_name": display_name,
                    "path": path_norm,
                    "source": source,
                    "raw_name": path_obj.name,
                }
            )

    return out


def load_mask_background_library(cache_root: Path | None = None) -> list[dict[str, Any]]:
    """
    Ưu tiên lọc theo thuộc tính Favorite từ chính dữ liệu CapCut.
    Nếu chưa map được favorite -> fallback toàn bộ onlineMaterial.
    """
    if cache_root is None:
        cache_root = DEFAULT_MASK_BG_CACHE_ROOT

    # vẫn seed pack vào cache để backward-compatible, nhưng KHÔNG đưa vào library mặc định
    seed_mask_background_cache(cache_root=cache_root)

    global_fav_ids = _collect_global_favorite_material_ids()
    favorite_items = _collect_favorite_background_items_from_projects(global_favorite_ids=global_fav_ids)
    if favorite_items:
        return favorite_items

    online_videos = _iter_video_files_recursive(DEFAULT_ONLINE_MATERIAL_ROOT, max_items=4000)
    return _library_from_paths(online_videos, source="onlineMaterial")
