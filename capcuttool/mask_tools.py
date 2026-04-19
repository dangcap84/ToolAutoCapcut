from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
_DEFAULT_ONLINE_MATERIAL_ROOT = Path(
    os.environ.get("USERPROFILE", "C:/Users/Admin")
) / "AppData" / "Local" / "CapCut" / "User Data" / "Cache" / "onlineMaterial"

# Baseline thực tế rút ra từ project mask chuẩn (Test1-mask):
# 1800px -> width 1.2784090909 => base_w ~= 1408
#  928px -> height 1.2083333333 => base_h ~= 768
# Dùng baseline này giúp size khớp UI CapCut khi chỉnh mask.
_MASK_BASELINE_W = 1408.0
_MASK_BASELINE_H = 768.0


def _new_id() -> str:
    return str(uuid4()).upper()


def _clone(obj: dict[str, Any] | None) -> dict[str, Any]:
    return copy.deepcopy(obj) if isinstance(obj, dict) else {}


def _get_canvas_size(draft: dict[str, Any]) -> tuple[float, float]:
    cfg = draft.get("canvas_config") if isinstance(draft, dict) else None
    w = float((cfg or {}).get("width") or 1920)
    h = float((cfg or {}).get("height") or 1080)
    return max(1.0, w), max(1.0, h)


def _select_main_video_track(draft: dict[str, Any]) -> dict[str, Any] | None:
    tracks = draft.get("tracks")
    if not isinstance(tracks, list):
        return None

    candidates: list[tuple[int, dict[str, Any]]] = []
    for tr in tracks:
        if not isinstance(tr, dict):
            continue
        if str(tr.get("type") or "").lower() != "video":
            continue
        segs = tr.get("segments")
        if not isinstance(segs, list):
            continue
        flag = int(tr.get("flag") or 0)
        # Ưu tiên track chính (flag=0), rồi tới track có nhiều segment nhất.
        score = (1 if flag == 0 else 0, len(segs))
        candidates.append((score[0] * 10_000 + score[1], tr))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _find_video_track_segment(draft: dict[str, Any] | None, *, flag: int) -> dict[str, Any] | None:
    if not isinstance(draft, dict):
        return None
    tracks = draft.get("tracks")
    if not isinstance(tracks, list):
        return None
    for tr in tracks:
        if not isinstance(tr, dict):
            continue
        if str(tr.get("type") or "").lower() != "video":
            continue
        if int(tr.get("flag") or 0) != int(flag):
            continue
        segs = tr.get("segments")
        if isinstance(segs, list) and segs and isinstance(segs[0], dict):
            return _clone(segs[0])
    return None


def _ensure_video_track(draft: dict[str, Any], *, flag: int) -> dict[str, Any]:
    tracks = draft.get("tracks")
    if not isinstance(tracks, list):
        tracks = []
        draft["tracks"] = tracks

    for tr in tracks:
        if not isinstance(tr, dict):
            continue
        if str(tr.get("type") or "").lower() != "video":
            continue
        if int(tr.get("flag") or 0) == flag:
            if not isinstance(tr.get("segments"), list):
                tr["segments"] = []
            return tr

    tr = {
        "id": _new_id(),
        "type": "video",
        "name": "",
        "segments": [],
        "flag": int(flag),
    }
    tracks.append(tr)
    return tr


def _sum_video_track_duration_us(track: dict[str, Any]) -> int:
    segs = track.get("segments")
    if not isinstance(segs, list):
        return 0
    total = 0
    for seg in segs:
        if not isinstance(seg, dict):
            continue
        tr = seg.get("target_timerange") or {}
        start = int(tr.get("start") or 0)
        dur = int(tr.get("duration") or 0)
        total = max(total, start + max(0, dur))
    return total


def _build_mask_material(
    *,
    overlay_width: float,
    overlay_height: float,
    round_corner: float,
    mode: str,
    canvas_w: float,
    canvas_h: float,
    template_mask: dict[str, Any] | None,
) -> dict[str, Any]:
    obj = _clone(template_mask)
    if not obj:
        # Fallback schema gần với draft thật của CapCut để UI mask có thể chọn shape,
        # chỉnh size/position ổn định ngay cả khi không có template Test1-mask.
        obj = {
            "id": "",
            "type": "mask",
            "name": "Hình chữ nhật",
            "resource_type": "rectangle",
            "resource_id": "7374021450748924432",
            "category": "",
            "category_id": "",
            "category_name": "",
            "constant_material_id": "",
            "contour_path": "",
            "loader_work_space": "",
            "panel": "",
            "path": "",
            "platform": 0,
            "position_info": "",
            "source_platform": 0,
            "text_config": "",
            "track_segment": "",
            "is_old_version": False,
            "config": {},
        }

    obj["id"] = _new_id()
    obj["type"] = "mask"
    obj.setdefault("name", "Hình chữ nhật")
    obj.setdefault("resource_type", "rectangle")
    obj.setdefault("resource_id", "7374021450748924432")

    obj.setdefault("category", "video")
    obj.setdefault("platform", "all")
    obj.setdefault("source_platform", 0)
    obj.setdefault("is_old_version", False)

    cfg = obj.get("config") if isinstance(obj.get("config"), dict) else {}
    mode_norm = str(mode or "params").strip().lower()
    if mode_norm == "ratio":
        # Mode tỉ lệ: map trực tiếp theo khung hình (90 => 0.9 khung), tránh tràn.
        w_norm = max(0.01, float(overlay_width) / max(1.0, float(canvas_w)))
        h_norm = max(0.01, float(overlay_height) / max(1.0, float(canvas_h)))
    else:
        # Mode thông số: giữ baseline mask-space để khớp behavior thực tế trước đó.
        # (Không clamp max=1.0 vì có case width/height > 1.0 vẫn hợp lệ.)
        w_norm = max(0.01, float(overlay_width) / _MASK_BASELINE_W)
        h_norm = max(0.01, float(overlay_height) / _MASK_BASELINE_H)
    cfg["width"] = w_norm
    cfg["height"] = h_norm
    # Giữ đúng tỷ lệ theo input W/H để kích thước hiển thị khớp thiết lập.
    cfg["aspectRatio"] = float(w_norm / max(1e-6, h_norm))
    cfg.setdefault("centerX", 0.0)
    cfg.setdefault("centerY", 0.0)
    cfg.setdefault("rotation", 0.0)
    cfg.setdefault("feather", 0.0)
    cfg.setdefault("expansion", 0.0)
    cfg.setdefault("invert", False)
    # CapCut lưu roundCorner theo thang 0..1. Chuẩn hóa chắc chắn để tránh stale dữ liệu.
    rc = max(0.0, min(100.0, float(round_corner))) / 100.0
    cfg["roundCorner"] = rc
    obj["config"] = cfg
    return obj


def _build_combination_material(
    *,
    total_duration_us: int,
    template_video: dict[str, Any] | None,
) -> dict[str, Any]:
    vm = _clone(template_video)
    vm["id"] = _new_id()
    vm["type"] = "video"
    vm["path"] = ""
    vm["media_path"] = ""
    vm["material_id"] = ""
    vm["origin_material_id"] = ""
    vm["local_material_id"] = ""
    vm["local_id"] = ""
    vm["extra_type_option"] = 2
    vm["duration"] = int(total_duration_us)
    vm["material_name"] = "Clip ghép mask"
    vm.setdefault("has_audio", True)
    vm.setdefault("source_platform", 0)
    vm.setdefault("category_id", "")
    vm.setdefault("category_name", "")
    return vm


def _build_draft_material(
    *,
    base_before_mask: dict[str, Any],
    total_duration_us: int,
    template_draft_material: dict[str, Any] | None,
) -> dict[str, Any]:
    dm = _clone(template_draft_material)
    dm["id"] = _new_id()
    dm["type"] = "combination"
    dm.setdefault("combination_type", "none")
    dm.setdefault("combination_id", "")
    dm.setdefault("name", "Clip ghép mask")
    dm.setdefault("category_id", "")
    dm.setdefault("category_name", "")
    dm.setdefault("formula_id", "")
    dm.setdefault("draft_file_path", "")
    dm.setdefault("draft_cover_path", "")
    dm.setdefault("draft_config_path", "")
    dm.setdefault("precompile_combination", False)
    dm.setdefault("aimusic_mv_template_info", "")

    # Luôn lấy draft hiện tại của project làm base để tránh bị kéo media/template
    # từ project mẫu (vd Test1-mask) sang project đích.
    nested = copy.deepcopy(base_before_mask)
    nested["duration"] = int(total_duration_us)

    cfg = nested.get("canvas_config") if isinstance(nested.get("canvas_config"), dict) else {}
    src_cfg = base_before_mask.get("canvas_config") if isinstance(base_before_mask.get("canvas_config"), dict) else {}
    if src_cfg:
        cfg["width"] = src_cfg.get("width", cfg.get("width", 1920))
        cfg["height"] = src_cfg.get("height", cfg.get("height", 1080))
        cfg["ratio"] = src_cfg.get("ratio", cfg.get("ratio", "original"))
    nested["canvas_config"] = cfg

    dm["draft"] = nested
    return dm


def _ensure_material_list(materials: dict[str, Any], key: str) -> list[dict[str, Any]]:
    cur = materials.get(key)
    if not isinstance(cur, list):
        cur = []
        materials[key] = cur
    return cur


def _is_video_material(mat: dict[str, Any]) -> bool:
    if not isinstance(mat, dict):
        return False

    path = str(mat.get("path") or "")
    ext = Path(path).suffix.lower()
    if ext in _IMAGE_EXTS:
        return False
    if ext in _VIDEO_EXTS:
        return True

    mtype = str(mat.get("type") or "").lower()
    # fallback: path không có ext rõ ràng thì mới dựa vào type
    return mtype == "video"


def _pick_video_material_template(
    materials: dict[str, Any],
    template_materials: dict[str, Any],
) -> dict[str, Any]:
    for src in [materials.get("videos"), template_materials.get("videos")]:
        if not isinstance(src, list):
            continue
        for item in src:
            if _is_video_material(item):
                return _clone(item)
    return {}


def _ensure_support_material(
    materials: dict[str, Any],
    key: str,
    default_obj: dict[str, Any],
) -> str:
    arr = _ensure_material_list(materials, key)
    if arr and isinstance(arr[0], dict) and arr[0].get("id"):
        return str(arr[0]["id"])

    obj = _clone(default_obj)
    obj["id"] = _new_id()
    arr.append(obj)
    return str(obj["id"])


def _ensure_segment_support_refs(materials: dict[str, Any], include_mask_id: str | None = None, include_draft_id: str | None = None) -> list[str]:
    refs: list[str] = []

    if include_draft_id:
        refs.append(include_draft_id)

    refs.append(_ensure_support_material(materials, "speeds", {"type": "speed", "speed": 1.0, "mode": 0, "curve_speed": None}))
    refs.append(_ensure_support_material(materials, "placeholder_infos", {"type": "placeholder_info", "error_path": "", "error_text": "", "meta_type": "none", "res_path": "", "res_text": ""}))

    # Giữ thứ tự refs khớp project mask chuẩn: draft,speed,placeholder,mask,canvas,...
    if include_mask_id:
        refs.append(include_mask_id)

    refs.append(_ensure_support_material(materials, "canvases", {"type": "canvas_color", "color": "", "image": "", "image_id": "", "image_name": "", "blur": 0.0, "album_image": "", "source_platform": 0, "team_id": ""}))

    refs.append(_ensure_support_material(materials, "sound_channel_mappings", {"type": "none", "audio_channel_mapping": 0, "is_config_open": False}))
    refs.append(_ensure_support_material(materials, "material_colors", {"solid_color": "", "is_gradient": False, "gradient_angle": 90.0, "gradient_colors": [], "gradient_percents": [], "is_color_clip": False, "width": 0.0, "height": 0.0}))
    refs.append(_ensure_support_material(materials, "vocal_separations", {"type": "vocal_separation"}))

    return refs


def _collect_transition_ids(materials: dict[str, Any]) -> set[str]:
    transitions = materials.get("transitions") if isinstance(materials, dict) else None
    out: set[str] = set()
    if isinstance(transitions, list):
        for t in transitions:
            if isinstance(t, dict):
                tid = str(t.get("id") or "").strip()
                if tid:
                    out.add(tid)
    return out


def _merge_refs_keep_order(primary: list[str], secondary: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for src in (primary, secondary):
        for rid in src:
            sid = str(rid or "").strip()
            if not sid or sid in seen:
                continue
            seen.add(sid)
            out.append(sid)
    return out


def _resolve_background_path_for_capcut(path_str: str) -> str:
    p = Path(path_str)
    if not p.name:
        return str(p).replace("\\", "/")

    # Khi source từ embedded-pack, ưu tiên/ép trỏ về onlineMaterial để tránh
    # case CapCut báo media unsupported ở một số project.
    try:
        lower_parts = [x.lower() for x in p.parts]
    except Exception:
        lower_parts = []

    if "mask_background_pack" in lower_parts:
        cand = _DEFAULT_ONLINE_MATERIAL_ROOT / p.name
        if cand.exists() and cand.is_file():
            return str(cand).replace("\\", "/")

        # Không có trong onlineMaterial thì tự copy sang đó.
        try:
            _DEFAULT_ONLINE_MATERIAL_ROOT.mkdir(parents=True, exist_ok=True)
            if p.exists() and p.is_file():
                shutil.copy2(p, cand)
                if cand.exists() and cand.is_file():
                    return str(cand).replace("\\", "/")
        except Exception:
            pass

        # Fallback: dò theo tên trong onlineMaterial (nếu có bản khác thư mục con).
        try:
            for hit in _DEFAULT_ONLINE_MATERIAL_ROOT.rglob(p.name):
                if hit.is_file():
                    return str(hit).replace("\\", "/")
        except Exception:
            pass

    return str(p).replace("\\", "/")


def _register_background_catalog(paths: list[str], catalog_path: Path | None) -> int:
    if catalog_path is None:
        return 0

    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    if catalog_path.exists():
        try:
            raw = json.loads(catalog_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                items = [x for x in raw if isinstance(x, dict)]
        except Exception:
            items = []

    by_path = {str((x.get("path") or "")).lower(): x for x in items}
    added = 0
    for p in paths:
        key = str(Path(p)).lower()
        if key in by_path:
            continue
        obj = {
            "id": _new_id(),
            "name": Path(p).name,
            "path": str(Path(p)).replace("\\", "/"),
            "added_at": "",
        }
        items.append(obj)
        by_path[key] = obj
        added += 1

    catalog_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return added


def _prune_existing_mask_overlay(draft: dict[str, Any]) -> None:
    if not isinstance(draft, dict):
        return
    tracks = draft.get("tracks")
    if not isinstance(tracks, list):
        return

    # Xóa overlay mask track cũ (flag=2) để tránh chồng/refs stale.
    draft["tracks"] = [
        tr
        for tr in tracks
        if not (isinstance(tr, dict) and str(tr.get("type") or "").lower() == "video" and int(tr.get("flag") or 0) == 2)
    ]


def apply_mask_to_draft(
    draft: dict[str, Any],
    *,
    overlay_width: float,
    overlay_height: float,
    round_corner: float = 20.0,
    mask_scale_percent: float = 100.0,
    mask_mode: str = "params",
    background_paths: list[str],
    template_draft: dict[str, Any] | None,
    background_catalog_path: Path | None,
) -> dict[str, int]:
    if not isinstance(draft, dict):
        return {"updated": 0, "bg_added": 0}

    tracks = draft.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        return {"updated": 0, "bg_added": 0}

    main_track = _select_main_video_track(draft)
    if main_track is None:
        return {"updated": 0, "bg_added": 0}

    main_segments = main_track.get("segments")
    if not isinstance(main_segments, list) or not main_segments:
        return {"updated": 0, "bg_added": 0}

    materials = draft.get("materials")
    if not isinstance(materials, dict):
        materials = {}
        draft["materials"] = materials

    _prune_existing_mask_overlay(draft)

    base_before_mask = copy.deepcopy(draft)

    videos = _ensure_material_list(materials, "videos")
    drafts = _ensure_material_list(materials, "drafts")
    masks = _ensure_material_list(materials, "common_mask")

    template_materials = template_draft.get("materials") if isinstance(template_draft, dict) else {}
    if not isinstance(template_materials, dict):
        template_materials = {}

    template_video_comb = None
    for v in template_materials.get("videos") or []:
        if isinstance(v, dict) and int(v.get("extra_type_option") or 0) == 2:
            template_video_comb = v
            break
    if template_video_comb is None and videos:
        template_video_comb = videos[0]

    template_draft_material = None
    tdrafts = template_materials.get("drafts") or []
    if tdrafts and isinstance(tdrafts[0], dict):
        template_draft_material = tdrafts[0]

    template_mask = None
    tmasks = template_materials.get("common_mask") or []
    if tmasks and isinstance(tmasks[0], dict):
        template_mask = tmasks[0]

    total_duration_us = _sum_video_track_duration_us(main_track)
    if total_duration_us <= 0:
        total_duration_us = sum(int((s.get("target_timerange") or {}).get("duration") or 0) for s in main_segments)
    total_duration_us = max(1, int(total_duration_us))

    canvas_w, canvas_h = _get_canvas_size(draft)

    mode = str(mask_mode or "params").strip().lower()
    if mode == "ratio":
        ratio = max(1.0, min(300.0, float(mask_scale_percent))) / 100.0
        overlay_width = float(canvas_w) * ratio
        overlay_height = float(canvas_h) * ratio

    comb_video = _build_combination_material(
        total_duration_us=total_duration_us,
        template_video=template_video_comb,
    )
    videos.append(comb_video)

    comb_draft = _build_draft_material(
        base_before_mask=base_before_mask,
        total_duration_us=total_duration_us,
        template_draft_material=template_draft_material,
    )
    # Liên kết 2 chiều để CapCut nhận combination material ổn định.
    comb_draft["combination_id"] = str(comb_video.get("id") or "")
    drafts.append(comb_draft)

    mask_mat = _build_mask_material(
        overlay_width=overlay_width,
        overlay_height=overlay_height,
        round_corner=round_corner,
        mode=mode,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
        template_mask=template_mask,
    )
    masks.append(mask_mat)

    # 1) line chính: thay bằng background nếu user có truyền vào.
    bg_paths = [
        _resolve_background_path_for_capcut(str(p).strip())
        for p in background_paths
        if str(p).strip()
    ]
    bg_added = _register_background_catalog(bg_paths, background_catalog_path)

    # Background/main line không được gắn mask ref, nếu không sẽ bị ăn mask ngoài ý muốn.
    seg_support_refs = _ensure_segment_support_refs(materials)
    transition_ids = _collect_transition_ids(materials)

    if bg_paths:
        seg_template = _clone(main_segments[0])
        vm_template = _pick_video_material_template(materials, template_materials)

        bg_ids: list[str] = []
        for p in bg_paths:
            norm_p = str(Path(p)).replace("\\", "/")
            vm = _clone(vm_template)
            vm["id"] = _new_id()
            vm["type"] = "video"
            vm["path"] = norm_p
            vm["media_path"] = norm_p
            vm["material_name"] = Path(norm_p).name
            vm["duration"] = int(total_duration_us)
            vm["extra_type_option"] = int(vm.get("extra_type_option") or 0)
            vm["has_audio"] = bool(vm.get("has_audio") or False)

            # tránh giữ metadata ràng buộc vào source video cũ
            vm["material_id"] = ""
            vm["origin_material_id"] = ""
            vm["local_material_id"] = ""
            vm["local_id"] = ""
            vm["reverse_path"] = ""
            vm["intensifies_path"] = ""
            vm["reverse_intensifies_path"] = ""

            videos.append(vm)
            bg_ids.append(vm["id"])

        rebuilt: list[dict[str, Any]] = []
        for idx, old_seg in enumerate(main_segments):
            old_target = old_seg.get("target_timerange") if isinstance(old_seg, dict) else {}
            old_source = old_seg.get("source_timerange") if isinstance(old_seg, dict) else {}

            start = int((old_target or {}).get("start") or 0)
            dur = int((old_target or {}).get("duration") or 0)
            dur = max(1, dur)

            src_start = int((old_source or {}).get("start") or 0)
            src_dur = int((old_source or {}).get("duration") or 0)
            if src_dur <= 0:
                src_dur = dur

            seg = _clone(seg_template)
            seg["id"] = _new_id()
            seg["material_id"] = bg_ids[idx % len(bg_ids)]
            # Giữ nguyên timing của từng segment theo project gốc (không nén timeline).
            seg["target_timerange"] = {"start": int(start), "duration": int(dur)}
            seg["source_timerange"] = {"start": int(src_start), "duration": int(src_dur)}
            seg["render_index"] = 0
            seg["track_render_index"] = 0
            seg["enable_video_mask"] = True
            seg["enable_adjust_mask"] = True
            old_refs = seg.get("extra_material_refs") if isinstance(seg.get("extra_material_refs"), list) else []
            keep_transition_refs = [r for r in old_refs if str(r) in transition_ids]
            seg["extra_material_refs"] = _merge_refs_keep_order(keep_transition_refs, list(seg_support_refs))
            rebuilt.append(seg)

        main_track["segments"] = rebuilt
    else:
        for seg in main_segments:
            if isinstance(seg, dict):
                seg["enable_video_mask"] = True
                seg["enable_adjust_mask"] = True
                old_refs = seg.get("extra_material_refs") if isinstance(seg.get("extra_material_refs"), list) else []
                keep_transition_refs = [r for r in old_refs if str(r) in transition_ids]
                seg["extra_material_refs"] = _merge_refs_keep_order(keep_transition_refs, list(seg_support_refs))

    # 2) tạo track trên cùng chứa 1 clip combination + mask.
    top_track = _ensure_video_track(draft, flag=2)

    # Ưu tiên schema segment từ template flag=2 để đảm bảo mask editable (shape/size).
    # Nếu không có template thì mới fallback từ main segment và reset các trường dễ gây nhiễu.
    template_top_seg = _find_video_track_segment(template_draft, flag=2)
    top_seg = _clone(template_top_seg) if isinstance(template_top_seg, dict) else _clone(main_segments[0])
    top_seg["id"] = _new_id()
    top_seg["material_id"] = comb_video["id"]
    top_seg["target_timerange"] = {"start": 0, "duration": int(total_duration_us)}
    top_seg["source_timerange"] = {"start": 0, "duration": int(total_duration_us)}
    top_seg["render_index"] = 1
    top_seg["track_render_index"] = 2
    top_seg["enable_video_mask"] = True
    top_seg["enable_adjust_mask"] = True

    # reset các cấu phần có thể khiến CapCut coi segment là clip đã bake keyframe,
    # từ đó không cho chỉnh shape/size mask như mong muốn.
    mask_scale = max(1.0, min(300.0, float(mask_scale_percent))) / 100.0
    top_seg["clip"] = {
        "alpha": 1.0,
        "flip": {"horizontal": False, "vertical": False},
        "rotation": 0.0,
        "scale": {"x": float(mask_scale), "y": float(mask_scale)},
        "transform": {"x": 0.0, "y": 0.0},
    }
    top_seg["common_keyframes"] = []
    top_seg["keyframe_refs"] = []
    # Bắt buộc bật adjust mask để CapCut hiện UI shape + bo góc.
    top_seg["enable_adjust_mask"] = True

    refs = _ensure_segment_support_refs(materials, include_mask_id=mask_mat["id"], include_draft_id=comb_draft["id"])
    top_seg["extra_material_refs"] = refs

    top_track["segments"] = [top_seg]

    for k in ["duration", "tm_duration", "max_duration", "draft_duration"]:
        if isinstance(draft.get(k), (int, float)):
            draft[k] = int(total_duration_us)

    return {"updated": 1, "bg_added": int(bg_added)}
