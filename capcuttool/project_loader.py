from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List


@dataclass
class ProjectBundle:
    project_dir: Path
    main_draft_path: Path
    timeline_draft_paths: List[Path]
    meta_path: Path | None
    main_draft: Dict[str, Any]
    timelines: Dict[Path, Dict[str, Any]]
    meta: Dict[str, Any] | None


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _find_timeline_drafts(project_dir: Path) -> List[Path]:
    timelines_dir = project_dir / "Timelines"
    if not timelines_dir.exists():
        return []
    out: List[Path] = []
    for child in timelines_dir.iterdir():
        p = child / "draft_content.json"
        if child.is_dir() and p.exists():
            out.append(p)
    return sorted(out)


def load_project(project_dir: Path) -> ProjectBundle:
    if not project_dir.exists() or not project_dir.is_dir():
        raise FileNotFoundError(f"Project not found: {project_dir}")

    main_draft_path = project_dir / "draft_content.json"
    if not main_draft_path.exists():
        raise FileNotFoundError(f"Missing file: {main_draft_path}")

    meta_path = project_dir / "draft_meta_info.json"
    meta = _read_json(meta_path) if meta_path.exists() else None

    timeline_paths = _find_timeline_drafts(project_dir)
    main_draft = _read_json(main_draft_path)
    timelines = {p: _read_json(p) for p in timeline_paths}

    return ProjectBundle(
        project_dir=project_dir,
        main_draft_path=main_draft_path,
        timeline_draft_paths=timeline_paths,
        meta_path=meta_path if meta_path.exists() else None,
        main_draft=main_draft,
        timelines=timelines,
        meta=meta,
    )
