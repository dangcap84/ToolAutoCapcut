from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS


@dataclass
class SceneMedia:
    index: int
    image_path: Path
    voice_path: Path


def _extract_index(name: str) -> int:
    nums = re.findall(r"\d+", name)
    if not nums:
        return -1
    return int(nums[-1])


def _scan_dir(folder: Path, exts: set[str]) -> List[Path]:
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts]
    return sorted(files, key=lambda p: (_extract_index(p.stem), p.name.lower()))


def build_scene_pairs(images_dir: Path, voices_dir: Path) -> List[SceneMedia]:
    images = _scan_dir(images_dir, MEDIA_EXTS)
    voices = _scan_dir(voices_dir, AUDIO_EXTS)

    if not images:
        raise ValueError(f"No image/video files found in: {images_dir}")
    if not voices:
        raise ValueError(f"No voice files found in: {voices_dir}")

    # Không ép số lượng file media phải bằng voice.
    # Mapping chỉ phục vụ pipeline đồng bộ (timeline sẽ normalize theo voice duration).
    # - media nhiều hơn voice: dùng phần đầu theo thứ tự, file dư vẫn giữ nguyên trong project folder
    # - media ít hơn voice: lặp media cuối để luôn có mapping 1-1 theo thứ tự
    scenes: List[SceneMedia] = []
    last_img = images[-1]
    for pos, voc in enumerate(voices, start=1):
        img = images[pos - 1] if pos <= len(images) else last_img
        scenes.append(SceneMedia(index=pos, image_path=img, voice_path=voc))
    return scenes
