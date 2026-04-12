from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


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
    images = _scan_dir(images_dir, IMAGE_EXTS)
    voices = _scan_dir(voices_dir, AUDIO_EXTS)

    if not images:
        raise ValueError(f"No image files found in: {images_dir}")
    if not voices:
        raise ValueError(f"No voice files found in: {voices_dir}")
    if len(images) != len(voices):
        raise ValueError(
            f"Image/voice count mismatch: images={len(images)}, voices={len(voices)}. "
            "Refusing to auto-guess."
        )

    scenes: List[SceneMedia] = []
    for img, voc in zip(images, voices):
        i_img = _extract_index(img.stem)
        i_voc = _extract_index(voc.stem)

        has_img_index = i_img != -1
        has_voc_index = i_voc != -1
        if has_img_index != has_voc_index:
            raise ValueError(
                "Inconsistent scene naming: one file has numeric index while the paired file does not. "
                f"image={img.name} voice={voc.name}."
            )

        if has_img_index and has_voc_index and i_img != i_voc:
            raise ValueError(
                f"Scene index mismatch: {img.name} (#{i_img}) vs {voc.name} (#{i_voc})."
            )

        idx = i_img if has_img_index else len(scenes) + 1
        scenes.append(SceneMedia(index=idx, image_path=img, voice_path=voc))
    return scenes
