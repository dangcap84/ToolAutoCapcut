from __future__ import annotations

import json
import random
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from builtin_transition_catalog import BUILTIN_TRANSITION_CATALOG

BUILTIN_TRANSITION_IDS = {
    str(x.get("effect_id") or "").strip()
    for x in BUILTIN_TRANSITION_CATALOG
    if str(x.get("effect_id") or "").strip()
}

USER_TRANSITION_LIBRARY_DRAFT = Path(
    "C:/Users/Admin/AppData/Local/CapCut/User Data/Projects/com.lveditor.draft/Transition-Library/draft_content.json"
)


DEFAULT_EFFECT_CACHE_ROOT = Path(
    "C:/Users/Admin/AppData/Local/CapCut/User Data/Cache/effect"
)

DEFAULT_EFFECT_PACK_ROOT = Path(__file__).resolve().parent / "transition_effect_pack"
DEFAULT_EFFECT_PACK_ZIP = Path(__file__).resolve().parent / "transition_effect_pack.zip"


def _candidate_effect_pack_roots() -> List[Path]:
    roots: List[Path] = [DEFAULT_EFFECT_PACK_ROOT]

    # When frozen (PyInstaller), prefer folder next to the EXE.
    if getattr(sys, "frozen", False):
        try:
            exe_dir = Path(sys.executable).resolve().parent
            roots.insert(0, exe_dir / "transition_effect_pack")
        except Exception:
            pass

    # De-duplicate while preserving order.
    out: List[Path] = []
    seen = set()
    for r in roots:
        k = str(r)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def _iter_effect_dirs(effect_cache_root: Path) -> List[Path]:
    if not effect_cache_root.exists() or not effect_cache_root.is_dir():
        return []

    out: List[Path] = []
    for child in sorted(effect_cache_root.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        if not child.name.isdigit():
            continue
        out.append(child)
    return out


def _pick_effect_path(effect_dir: Path) -> str:
    candidates = sorted([p for p in effect_dir.iterdir() if p.is_dir()], key=lambda p: p.name)
    if not candidates:
        return str(effect_dir)

    for c in candidates:
        if c.name.endswith("_tmp"):
            continue
        return str(c)
    return str(candidates[0])


def _read_json_if_exists(path: Path) -> Dict[str, Any] | None:
    try:
        if not path.exists() or not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _scan_first_text_value(obj: Any, candidate_keys: set[str]) -> str:
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            if lk in candidate_keys and isinstance(v, str):
                vv = v.strip()
                if vv:
                    return vv
        for v in obj.values():
            got = _scan_first_text_value(v, candidate_keys)
            if got:
                return got
    elif isinstance(obj, list):
        for v in obj:
            got = _scan_first_text_value(v, candidate_keys)
            if got:
                return got
    return ""


def _extract_effect_name_and_category(effect_dir: Path, chosen_path: Path) -> tuple[str, str]:
    candidate_files = [
        chosen_path / "config.json",
        chosen_path / "extra.json",
        effect_dir / "config.json",
        effect_dir / "extra.json",
    ]

    name = ""
    category = ""

    name_keys = {
        "name",
        "display_name",
        "effect_name",
        "transition_name",
        "title",
        "material_name",
        "local_name",
    }
    category_keys = {
        "category_name",
        "category",
        "categorytitle",
        "group_name",
    }

    for f in candidate_files:
        data = _read_json_if_exists(f)
        if not isinstance(data, (dict, list)):
            continue
        if not name:
            name = _scan_first_text_value(data, name_keys)
        if not category:
            category = _scan_first_text_value(data, category_keys)

    return name, category


def _catalog_from_effect_cache(effect_cache_root: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for d in _iter_effect_dirs(effect_cache_root):
        effect_id = d.name
        if BUILTIN_TRANSITION_IDS and effect_id not in BUILTIN_TRANSITION_IDS:
            continue
        chosen_path = Path(_pick_effect_path(d))
        name, category = _extract_effect_name_and_category(d, chosen_path)

        out.append(
            {
                "effect_id": effect_id,
                "resource_id": effect_id,
                "third_resource_id": effect_id,
                "name": name or effect_id,
                "category_id": "",
                "category_name": category or "",
                "path": str(chosen_path),
                "platform": "all",
                "source_platform": 1,
                "duration": 800_000,
                "is_overlap": True,
                "is_ai_transition": False,
            }
        )
    return out


def _catalog_from_project(draft: Dict[str, Any]) -> List[Dict[str, Any]]:
    mats = draft.get("materials")
    if not isinstance(mats, dict):
        return []

    transitions = mats.get("transitions")
    if not isinstance(transitions, list):
        return []

    out: List[Dict[str, Any]] = []
    for t in transitions:
        if not isinstance(t, dict):
            continue
        effect_id = str(t.get("effect_id") or "").strip()
        if not effect_id:
            continue
        out.append(
            {
                "effect_id": effect_id,
                "resource_id": str(t.get("resource_id") or effect_id),
                "third_resource_id": str(t.get("third_resource_id") or effect_id),
                "name": str(t.get("name") or effect_id),
                "category_id": str(t.get("category_id") or ""),
                "category_name": str(t.get("category_name") or ""),
                "path": str(t.get("path") or ""),
                "platform": str(t.get("platform") or "all"),
                "source_platform": int(t.get("source_platform") or 1),
                "duration": int(t.get("duration") or 800_000),
                "is_overlap": bool(t.get("is_overlap", True)),
                "is_ai_transition": bool(t.get("is_ai_transition", False)),
            }
        )
    return out


def _read_project_draft_file(path: Path) -> Dict[str, Any] | None:
    try:
        if not path.exists() or not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _candidate_effect_pack_zips() -> List[Path]:
    zips: List[Path] = [DEFAULT_EFFECT_PACK_ZIP]

    if getattr(sys, "frozen", False):
        try:
            exe_dir = Path(sys.executable).resolve().parent
            zips.insert(0, exe_dir / "transition_effect_pack.zip")
        except Exception:
            pass

        # PyInstaller onefile extracts bundled data to _MEIPASS at runtime.
        try:
            meipass = Path(getattr(sys, "_MEIPASS", ""))
            if str(meipass):
                zips.insert(0, meipass / "transition_effect_pack.zip")
        except Exception:
            pass

    out: List[Path] = []
    seen = set()
    for p in zips:
        k = str(p)
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


def seed_effect_cache_from_zip(
    zip_path: Path,
    effect_cache_root: Path | None = None,
) -> int:
    if effect_cache_root is None:
        effect_cache_root = DEFAULT_EFFECT_CACHE_ROOT

    try:
        effect_cache_root.mkdir(parents=True, exist_ok=True)
    except Exception:
        return 0

    if not zip_path.exists() or not zip_path.is_file():
        return 0

    extracted_effect_ids: set[str] = set()
    skipped_existing: set[str] = set()

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                raw = info.filename.replace("\\", "/")
                if not raw or raw.endswith("/"):
                    continue

                parts = [p for p in raw.split("/") if p and p not in {".", ".."}]
                if not parts:
                    continue

                effect_id = ""
                effect_idx = -1
                for i, p in enumerate(parts):
                    if p.isdigit() and (not BUILTIN_TRANSITION_IDS or p in BUILTIN_TRANSITION_IDS):
                        effect_id = p
                        effect_idx = i
                        break

                if not effect_id or effect_idx < 0:
                    continue

                base_target = effect_cache_root / effect_id
                if base_target.exists() and effect_id not in extracted_effect_ids:
                    skipped_existing.add(effect_id)
                    continue

                rel_parts = parts[effect_idx + 1 :]
                if not rel_parts:
                    continue

                target = base_target.joinpath(*rel_parts)
                target.parent.mkdir(parents=True, exist_ok=True)

                with zf.open(info, "r") as src, open(target, "wb") as dst:
                    dst.write(src.read())

                extracted_effect_ids.add(effect_id)
    except Exception:
        return 0

    return len(extracted_effect_ids)


def seed_effect_cache_from_pack(
    effect_cache_root: Path | None = None,
    effect_pack_root: Path | None = None,
) -> int:
    if effect_cache_root is None:
        effect_cache_root = DEFAULT_EFFECT_CACHE_ROOT

    candidate_roots: List[Path]
    if effect_pack_root is not None:
        candidate_roots = [effect_pack_root]
    else:
        candidate_roots = _candidate_effect_pack_roots()

    try:
        effect_cache_root.mkdir(parents=True, exist_ok=True)
    except Exception:
        return 0

    copied = 0

    # First try zip packs (portable distribution artifact).
    for z in _candidate_effect_pack_zips():
        copied += seed_effect_cache_from_zip(z, effect_cache_root=effect_cache_root)

    for root in candidate_roots:
        if not root.exists() or not root.is_dir():
            continue
        for d in sorted(root.iterdir(), key=lambda p: p.name):
            if not d.is_dir() or not d.name.isdigit():
                continue
            if BUILTIN_TRANSITION_IDS and d.name not in BUILTIN_TRANSITION_IDS:
                continue
            target = effect_cache_root / d.name
            if target.exists():
                continue
            try:
                import shutil
                shutil.copytree(d, target)
                copied += 1
            except Exception:
                continue
    return copied


def load_transition_catalog(
    effect_cache_root: Path | None = None,
    sample_project_draft: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    catalog: List[Dict[str, Any]] = []

    # 1) Builtin curated list (portable across machines/users).
    catalog.extend(BUILTIN_TRANSITION_CATALOG)

    # 2) Source of truth from user curated library project in CapCut (optional enrichment).
    curated = _read_project_draft_file(USER_TRANSITION_LIBRARY_DRAFT)
    if isinstance(curated, dict):
        catalog.extend(_catalog_from_project(curated))

    # 3) Current selected project transitions for fallback/enrichment.
    if isinstance(sample_project_draft, dict):
        catalog.extend(_catalog_from_project(sample_project_draft))

    # 4) Local downloaded cache (optional, may have extra effects).
    if effect_cache_root is None:
        effect_cache_root = DEFAULT_EFFECT_CACHE_ROOT
    catalog.extend(_catalog_from_effect_cache(effect_cache_root))

    dedup: Dict[str, Dict[str, Any]] = {}
    for item in catalog:
        effect_id = str(item.get("effect_id") or "").strip()
        if not effect_id:
            continue
        if effect_id not in dedup:
            dedup[effect_id] = item
            continue

        # Prefer human-readable name from project transitions over raw numeric IDs.
        cur = dedup[effect_id]
        cur_name = str(cur.get("name") or "").strip()
        new_name = str(item.get("name") or "").strip()
        cur_is_raw_id = cur_name == effect_id
        new_is_raw_id = new_name == effect_id

        if cur_is_raw_id and not new_is_raw_id:
            dedup[effect_id] = item
            continue

        # Otherwise prefer entry with richer name/category/path.
        score_cur = int(bool(cur_name and cur_name != effect_id)) + int(bool(cur.get("category_name"))) + int(bool(cur.get("path")))
        score_new = int(bool(new_name and new_name != effect_id)) + int(bool(item.get("category_name"))) + int(bool(item.get("path")))
        if score_new >= score_cur:
            dedup[effect_id] = item

    out = list(dedup.values())
    out.sort(key=lambda x: (str(x.get("category_name") or ""), str(x.get("name") or x.get("effect_id") or "")))
    return out


def _select_video_track(draft: Dict[str, Any]) -> Dict[str, Any] | None:
    tracks = draft.get("tracks")
    if not isinstance(tracks, list):
        return None

    candidates: List[tuple[int, Dict[str, Any]]] = []
    for tr in tracks:
        t = str(tr.get("type") or tr.get("track_type") or "").lower()
        if t != "video":
            continue
        segs = tr.get("segments")
        if isinstance(segs, list):
            candidates.append((len(segs), tr))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _strip_old_transition_refs(draft: Dict[str, Any]) -> None:
    mats = draft.get("materials")
    if not isinstance(mats, dict):
        return

    transitions = mats.get("transitions")
    old_ids = {
        str(t.get("id"))
        for t in transitions
        if isinstance(t, dict) and str(t.get("id") or "").strip()
    } if isinstance(transitions, list) else set()

    vt = _select_video_track(draft)
    if vt is not None:
        for seg in (vt.get("segments") or []):
            refs = seg.get("extra_material_refs")
            if isinstance(refs, list) and old_ids:
                seg["extra_material_refs"] = [r for r in refs if r not in old_ids]

    mats["transitions"] = []


def apply_random_transitions_to_draft(
    draft: Dict[str, Any],
    catalog: List[Dict[str, Any]],
    selected_effect_ids: List[str] | None = None,
    duration_us: int = 800_000,
    seed: int | None = None,
) -> int:
    if not isinstance(draft, dict):
        return 0

    vt = _select_video_track(draft)
    if vt is None:
        return 0

    segs = vt.get("segments")
    if not isinstance(segs, list) or len(segs) < 2:
        return 0

    _strip_old_transition_refs(draft)

    mats = draft.get("materials")
    if not isinstance(mats, dict):
        mats = {}
        draft["materials"] = mats

    selected = [x.strip() for x in (selected_effect_ids or []) if x and x.strip()]

    catalog_by_id: Dict[str, Dict[str, Any]] = {}
    for c in catalog:
        effect_id = str(c.get("effect_id") or "").strip()
        if not effect_id:
            continue
        if effect_id not in catalog_by_id:
            catalog_by_id[effect_id] = c

    if selected:
        # Build pool from selected IDs directly so user selection is honored even if
        # some selected IDs are missing rich metadata in current catalog source.
        pool: List[Dict[str, Any]] = []
        for effect_id in selected:
            item = catalog_by_id.get(effect_id)
            if item is None:
                item = {
                    "effect_id": effect_id,
                    "resource_id": effect_id,
                    "third_resource_id": effect_id,
                    "name": effect_id,
                    "category_id": "",
                    "category_name": "",
                    "path": "",
                    "platform": "all",
                    "source_platform": 1,
                    "duration": int(duration_us or 800_000),
                    "is_overlap": True,
                    "is_ai_transition": False,
                }
            pool.append(item)
    else:
        pool = list(catalog_by_id.values())

    if not pool:
        return 0

    rng = random.Random(seed)
    transitions: List[Dict[str, Any]] = []
    prev_effect_id = ""

    for i in range(1, len(segs)):
        candidates = [c for c in pool if str(c.get("effect_id") or "").strip() != prev_effect_id]
        if not candidates:
            candidates = pool

        chosen = rng.choice(candidates)
        effect_id = str(chosen.get("effect_id") or "").strip()
        if not effect_id:
            continue

        tid = str(uuid4()).upper()
        item = {
            "id": tid,
            "type": "transition",
            "name": str(chosen.get("name") or effect_id),
            "effect_id": effect_id,
            "resource_id": str(chosen.get("resource_id") or effect_id),
            "third_resource_id": str(chosen.get("third_resource_id") or effect_id),
            "source_platform": int(chosen.get("source_platform") or 1),
            "path": str(chosen.get("path") or ""),
            "duration": int(chosen.get("duration") or duration_us or 800_000),
            "is_overlap": bool(chosen.get("is_overlap", True)),
            "platform": str(chosen.get("platform") or "all"),
            "category_id": str(chosen.get("category_id") or ""),
            "category_name": str(chosen.get("category_name") or ""),
            "request_id": "",
            "is_ai_transition": bool(chosen.get("is_ai_transition", False)),
            "video_path": "",
            "task_id": "",
        }
        transitions.append(item)

        # CapCut expects transition ref on the segment BEFORE the cut.
        seg = segs[i - 1]
        refs = seg.get("extra_material_refs")
        if not isinstance(refs, list):
            refs = []
            seg["extra_material_refs"] = refs
        refs.append(tid)
        prev_effect_id = effect_id

    mats["transitions"] = transitions
    return len(transitions)
