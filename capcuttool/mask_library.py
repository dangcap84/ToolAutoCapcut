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
DEFAULT_MASK_BG_CATALOG_PATH = Path(__file__).resolve().parent / "mask_background_catalog.json"
DEFAULT_CAPCUT_PROJECTS_ROOT = DEFAULT_CAPCUT_USER_DATA_ROOT / "Projects" / "com.lveditor.draft"

_MASK_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}

# Mapping tạm tên readable cho các onlineMaterial ID đã xác nhận.
# Dùng làm default fallback khi CapCut metadata bị thiếu/mất.
DEFAULT_ONLINE_MATERIAL_NAME_MAP: dict[str, str] = {
    "49ac9813cae7f6f87a6f03734efa0c3d.mp4": "Falling pink sakura flowers background animation. Abstract flat animation",
    "3f4a7cda779843780c180f6d95dd006d.mp4": "pexels-weldi-studio-design-8675587",
    "c3a921a326ee451dd6ef2fbe30cd9c10.mp4": "Cliff with waves crashing against a rocky shore, Nusa Penida, Indonesia.",
    "06daa67c2675769c8c2ba227468fc590.mp4": "Aerial Moscow District Buildings and houses Cityscape",
    "a168dee4e80d8b5703c88df2a480038f.mp4": "Flat Geometric Shapes Red",
    "ce97af96b65b7059597e06502f9765f1.mp4": "Bright neon seamless animation of heart sign. Design element for Happy Valentine's Day. For greeting card, banner, signboard. 4K video close-up.",
    "807205b8ffecf7f30bdbfa09db1b0277.mp4": "Seagulls on the beach",
    "e578e6f7e9aa548dc257f95f1ed2ae5b.mp4": "4K:Timelapse of the clear sky.",
    "81304eb1924b2452c1b64d23b1bb6d69.mp4": "Golden Sunset Reflected in Water of Tropical Beach",
    "daf89cec03e1d2c4cbbd24050a9287fd.mp4": "Falling snow particles isolated on black background",
    "5f7c5949617cf594f28e69e968a64bc8.mp4": "Minimal Motion Graphic Animation Of Lines Moving Up And Down On A Black",
}


def _is_readable_display_name(display_name: str, fallback_filename: str = "") -> bool:
    s = (display_name or "").strip()
    if not s:
        return False

    # ký tự lỗi decode/mojibake
    if "�" in s:
        return False

    # không chấp nhận khi chính display_name là hash/file-hash
    s_base = Path(s).name
    s_stem = Path(s_base).stem
    if re.fullmatch(r"[0-9a-f]{24,64}", s_stem.lower()):
        return False

    # nếu display_name trùng hệt filename hash thì cũng loại
    fb = Path(fallback_filename or "").name
    if fb and s_base.lower() == fb.lower() and re.fullmatch(r"[0-9a-f]{24,64}", Path(fb).stem.lower()):
        return False

    # bắt buộc có ít nhất 1 chữ cái (unicode ok)
    if not any(ch.isalpha() for ch in s):
        return False

    return True


def _best_effort_display_name(display_name: str, fallback_filename: str) -> str:
    preferred = (display_name or "").strip()
    if _is_readable_display_name(preferred, fallback_filename):
        return preferred

    stem_raw = Path(fallback_filename or "").stem
    stem = stem_raw.replace("_", " ").replace("-", " ").strip()
    if _is_readable_display_name(stem, fallback_filename):
        return stem

    # Không có tên chuẩn thì loại khỏi catalog.
    return ""


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


def _library_from_paths(
    paths: list[Path],
    source: str,
    display_name_by_basename: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    name_map = display_name_by_basename or {}

    # Ưu tiên file mới hơn để user thấy asset vừa tải về trước.
    paths = sorted(paths, key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)

    for p in paths:
        if not p.exists() or not p.is_file():
            continue
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)

        display_name = _best_effort_display_name(name_map.get(p.name.lower(), ""), p.name)
        if not display_name:
            continue

        out.append(
            {
                "name": p.name,
                "display_name": display_name,
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


def _load_mask_background_catalog(catalog_path: Path = DEFAULT_MASK_BG_CATALOG_PATH) -> list[dict[str, Any]]:
    raw = _safe_load_json(catalog_path)
    if not isinstance(raw, list):
        return []

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue

        p = str(item.get("path") or "").strip()
        if not p:
            continue

        pp = Path(p)
        if not pp.exists() or not pp.is_file():
            continue
        if pp.suffix.lower() not in _MASK_VIDEO_EXTS:
            continue

        key = str(pp).replace("\\", "/").lower()
        if key in seen:
            continue
        seen.add(key)

        display_name = _best_effort_display_name(str(item.get("display_name") or item.get("name") or ""), pp.name)
        if not display_name:
            continue

        out.append(
            {
                "name": pp.name,
                "display_name": display_name,
                "path": str(pp).replace("\\", "/"),
                "source": "catalog",
                "raw_name": pp.name,
            }
        )

    return out


def _save_mask_background_catalog(
    items: list[dict[str, Any]],
    catalog_path: Path = DEFAULT_MASK_BG_CATALOG_PATH,
) -> None:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in items:
        if not isinstance(item, dict):
            continue

        p = str(item.get("path") or "").strip()
        if not p:
            continue

        pp = Path(p)
        if pp.suffix.lower() not in _MASK_VIDEO_EXTS:
            continue

        path_norm = str(pp).replace("\\", "/")
        key = path_norm.lower()
        if key in seen:
            continue
        seen.add(key)

        display_name = _best_effort_display_name(str(item.get("display_name") or item.get("name") or ""), pp.name)
        if not display_name:
            continue

        rows.append(
            {
                "name": pp.name,
                "display_name": display_name,
                "path": path_norm,
            }
        )

    try:
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        catalog_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


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


def _collect_online_material_display_name_map(projects_root: Path = DEFAULT_CAPCUT_PROJECTS_ROOT) -> dict[str, str]:
    """
    Map filename hash trong onlineMaterial -> tên dễ đọc từ metadata project.
    Ưu tiên material_name, fallback materialName trong key_value.
    """
    out: dict[str, str] = {}
    project_dirs = _iter_capcut_project_dirs(projects_root)
    if not project_dirs:
        return out

    for proj in project_dirs:
        key_value_path = proj / "key_value.json"
        draft_content_path = proj / "draft_content.json"
        if not key_value_path.exists() or not draft_content_path.exists():
            continue

        key_data = _safe_load_json(key_value_path)
        key_name_by_mid: dict[str, str] = {}
        if isinstance(key_data, dict):
            for _, v in key_data.items():
                if not isinstance(v, dict):
                    continue
                mid = str(v.get("materialId") or "").strip()
                mname = str(v.get("materialName") or "").strip()
                if mid and mname and mid not in key_name_by_mid:
                    key_name_by_mid[mid] = mname

        draft_data = _safe_load_json(draft_content_path)
        if not isinstance(draft_data, dict):
            continue

        videos = ((draft_data.get("materials") or {}).get("videos") or [])
        if not isinstance(videos, list):
            continue

        for item in videos:
            if not isinstance(item, dict):
                continue

            raw_path = str(item.get("path") or item.get("media_path") or "").strip()
            if not raw_path or "onlinematerial" not in raw_path.lower():
                continue

            p = Path(raw_path)
            if p.suffix.lower() not in _MASK_VIDEO_EXTS:
                continue

            base_key = p.name.lower()
            if base_key in out:
                continue

            material_id = str(item.get("material_id") or "").strip()
            material_name = str(item.get("material_name") or "").strip()
            if not material_name and material_id:
                material_name = key_name_by_mid.get(material_id, "").strip()

            picked = _best_effort_display_name(material_name, p.name)
            if picked:
                out[base_key] = picked

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

            seeded_name = DEFAULT_ONLINE_MATERIAL_NAME_MAP.get(path_obj.name.lower(), "")
            display_name = _best_effort_display_name(
                str(item.get("material_name") or fav_ids.get(material_id) or seeded_name or ""),
                path_obj.name,
            )
            if not display_name:
                continue

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
    Chỉ load danh sách từ embedded-pack đã nhúng trong EXE.
    Không lấy thêm từ catalog/favorite/onlineMaterial.
    """
    if cache_root is None:
        cache_root = DEFAULT_MASK_BG_CACHE_ROOT

    # Seed pack nhúng ra cache runtime.
    seed_mask_background_cache(cache_root=cache_root)

    name_map = {k.lower(): v for k, v in DEFAULT_ONLINE_MATERIAL_NAME_MAP.items()}

    embedded_videos = _iter_video_files(cache_root)
    embedded_name_map: dict[str, str] = {}
    for p in embedded_videos:
        key = p.name.lower()
        mapped = _best_effort_display_name(name_map.get(key, ""), p.name)
        if mapped:
            embedded_name_map[key] = mapped

    out = _library_from_paths(
        embedded_videos,
        source="embedded-pack",
        display_name_by_basename=embedded_name_map,
    )

    # Persist chỉ đúng danh sách embedded để lần sau giữ nguyên.
    _save_mask_background_catalog(out)
    return out
