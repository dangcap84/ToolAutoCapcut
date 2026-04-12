from __future__ import annotations

import argparse
from pathlib import Path

from duration_probe import probe_audio_duration_seconds
from media_index import build_scene_pairs
from project_loader import load_project
from project_writer import backup_file, write_json_atomic
from timeline_sync import sec_to_us, sync_draft, sync_meta


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="CapCut draft sync tool (MVP)")
    p.add_argument("--project", required=True, help="CapCut project folder")
    p.add_argument("--images", required=False, help="Scene images folder (optional)")
    p.add_argument("--voices", required=False, help="Scene voices folder (optional)")
    p.add_argument("--mode", choices=["inspect", "sync"], default="inspect")
    p.add_argument("--backup", action="store_true", help="Create backup files before writing")
    return p


def _durations_from_media_folders(images: Path, voices: Path) -> list[int]:
    scenes = build_scene_pairs(images, voices)
    return [sec_to_us(probe_audio_duration_seconds(s.voice_path)) for s in scenes]


def _durations_from_project_audio_segments(project: Path) -> list[int]:
    bundle = load_project(project)
    tracks = bundle.main_draft.get("tracks")
    if not isinstance(tracks, list):
        raise ValueError("draft_content.json missing 'tracks' list")

    audio_tracks = [t for t in tracks if str(t.get("type") or t.get("track_type") or "").lower() == "audio"]
    if not audio_tracks:
        raise ValueError("No audio track found in draft to infer segment durations")

    audio_tracks.sort(key=lambda t: len(t.get("segments") or []))
    segs = audio_tracks[0].get("segments") or []
    if not segs:
        raise ValueError("Audio track has no segments")

    segs = sorted(segs, key=lambda s: int(((s.get("target_timerange") or {}).get("start") or 0)))
    out: list[int] = []
    for seg in segs:
        tgt = seg.get("target_timerange") or {}
        src = seg.get("source_timerange") or {}
        dur = int(tgt.get("duration") or src.get("duration") or 0)
        if dur > 0:
            out.append(dur)

    if not out:
        raise ValueError("Cannot infer any positive duration from audio segments")
    return out


def _resolve_durations(project: Path, images: Path | None, voices: Path | None) -> list[int]:
    if images is not None and voices is not None:
        return _durations_from_media_folders(images, voices)
    return _durations_from_project_audio_segments(project)


def run_inspect(project: Path, images: Path | None = None, voices: Path | None = None) -> int:
    bundle = load_project(project)
    durations_us = _resolve_durations(project, images, voices)

    print(f"project={bundle.project_dir}")
    print(f"main_draft={bundle.main_draft_path}")
    print(f"timeline_drafts={len(bundle.timeline_draft_paths)}")
    print(f"scenes={len(durations_us)}")
    print(f"duration_source={'media_folders' if images and voices else 'project_audio_segments'}")

    total = sum(durations_us)
    for i, us in enumerate(durations_us, start=1):
        print(f"scene#{i}: duration={us / 1_000_000:.3f}s ({us}us)")

    print(f"total_duration={total}us")
    return 0


def run_sync(project: Path, images: Path | None = None, voices: Path | None = None, backup: bool = False) -> int:
    bundle = load_project(project)
    durations_us = _resolve_durations(project, images, voices)

    changed_files = []
    backup_files = []

    if backup:
        backup_files.append(str(backup_file(bundle.main_draft_path)))
        for p in bundle.timeline_draft_paths:
            backup_files.append(str(backup_file(p)))
        if bundle.meta_path is not None and bundle.meta_path.exists():
            backup_files.append(str(backup_file(bundle.meta_path)))

    stats_main = sync_draft(bundle.main_draft, durations_us)
    write_json_atomic(bundle.main_draft_path, bundle.main_draft)
    changed_files.append(str(bundle.main_draft_path))

    for p in bundle.timeline_draft_paths:
        draft = bundle.timelines[p]
        sync_draft(draft, durations_us)
        write_json_atomic(p, draft)
        changed_files.append(str(p))

    if bundle.meta is not None and bundle.meta_path is not None:
        sync_meta(bundle.meta, stats_main.total_duration_us)
        write_json_atomic(bundle.meta_path, bundle.meta)
        changed_files.append(str(bundle.meta_path))

    print("sync_done=true")
    print(f"scenes={stats_main.scenes}")
    print(f"video_segments_updated={stats_main.video_segments_updated}")
    print(f"audio_segments_updated={stats_main.audio_segments_updated}")
    print(f"total_duration_us={stats_main.total_duration_us}")
    print("changed_files:")
    for f in changed_files:
        print(f" - {f}")

    if backup_files:
        print("backup_files:")
        for f in backup_files:
            print(f" - {f}")

    return 0


def main() -> int:
    args = build_parser().parse_args()
    project = Path(args.project)
    images = Path(args.images) if args.images else None
    voices = Path(args.voices) if args.voices else None

    if (images is None) ^ (voices is None):
        raise SystemExit("Provide both --images and --voices together, or provide neither.")

    if args.mode == "inspect":
        return run_inspect(project, images, voices)
    return run_sync(project, images, voices, args.backup)


if __name__ == "__main__":
    raise SystemExit(main())
