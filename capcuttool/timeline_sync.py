from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


@dataclass
class SyncStats:
    scenes: int
    video_segments_updated: int
    audio_segments_updated: int
    total_duration_us: int
    source_scenes: int


def sec_to_us(sec: float) -> int:
    return int(round(sec * 1_000_000))


def _track_type(track: Dict[str, Any]) -> str:
    t = str(track.get("type") or track.get("track_type") or "").lower()
    return t


def _segments_of(track: Dict[str, Any]) -> List[Dict[str, Any]]:
    segs = track.get("segments")
    return segs if isinstance(segs, list) else []


def _sort_by_target_start(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        segments,
        key=lambda s: int(((s.get("target_timerange") or {}).get("start") or 0)),
    )


def _select_track_with_segments(tracks: List[Dict[str, Any]], wanted: str, min_count: int) -> Dict[str, Any] | None:
    candidates: List[Tuple[int, Dict[str, Any]]] = []
    for tr in tracks:
        t = _track_type(tr)
        if wanted == "video" and t in {"audio", "effect", "text", "sticker"}:
            continue
        if wanted == "audio" and t != "audio":
            continue
        c = len(_segments_of(tr))
        if c >= min_count:
            candidates.append((c, tr))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def _select_track_with_most_segments(tracks: List[Dict[str, Any]], wanted: str) -> Dict[str, Any] | None:
    candidates: List[Tuple[int, Dict[str, Any]]] = []
    for tr in tracks:
        t = _track_type(tr)
        if wanted == "video" and t in {"audio", "effect", "text", "sticker"}:
            continue
        if wanted == "audio" and t != "audio":
            continue
        c = len(_segments_of(tr))
        if c > 0:
            candidates.append((c, tr))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _update_track_segments(track: Dict[str, Any], durations_us: List[int]) -> int:
    segs = _sort_by_target_start(_segments_of(track))
    count = min(len(segs), len(durations_us))
    cursor = 0
    for i in range(count):
        seg = segs[i]
        d = int(durations_us[i])

        tgt = seg.setdefault("target_timerange", {})
        tgt["start"] = cursor
        tgt["duration"] = d

        src = seg.setdefault("source_timerange", {})
        src["duration"] = d

        cursor += d
    return count


def _update_project_duration_fields(draft: Dict[str, Any], total_duration_us: int) -> None:
    for k in ["duration", "tm_duration", "max_duration", "draft_duration"]:
        if k in draft and isinstance(draft[k], (int, float)):
            draft[k] = int(total_duration_us)


def sync_draft(draft: Dict[str, Any], durations_us: List[int]) -> SyncStats:
    tracks = draft.get("tracks")
    if not isinstance(tracks, list):
        raise ValueError("draft_content.json missing 'tracks' list")

    source_scene_count = len(durations_us)

    video_track = _select_track_with_segments(tracks, "video", source_scene_count)
    if video_track is None:
        video_track = _select_track_with_most_segments(tracks, "video")
    if video_track is None:
        raise ValueError("Cannot find any usable video track")

    video_seg_count = len(_segments_of(video_track))
    if video_seg_count <= 0:
        raise ValueError("Chosen video track has no segments")

    effective_durations = durations_us[:video_seg_count]
    scene_count = len(effective_durations)
    total = sum(effective_durations)

    v_updated = _update_track_segments(video_track, effective_durations)

    audio_track = _select_track_with_segments(tracks, "audio", scene_count)
    if audio_track is None:
        audio_track = _select_track_with_most_segments(tracks, "audio")

    a_updated = 0
    if audio_track is not None:
        a_updated = _update_track_segments(audio_track, effective_durations)

    _update_project_duration_fields(draft, total)

    return SyncStats(
        scenes=scene_count,
        video_segments_updated=v_updated,
        audio_segments_updated=a_updated,
        total_duration_us=total,
        source_scenes=source_scene_count,
    )


def sync_meta(meta: Dict[str, Any], total_duration_us: int) -> None:
    for key in ["tm_duration", "duration", "max_duration", "draft_timeline_materials_size_"]:
        if key in meta and isinstance(meta[key], (int, float)):
            if key == "draft_timeline_materials_size_":
                continue
            meta[key] = int(total_duration_us)

    if "tm_draft_modified" in meta:
        import time

        meta["tm_draft_modified"] = int(time.time() * 1000)
