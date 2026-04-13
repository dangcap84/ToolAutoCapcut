from __future__ import annotations

import subprocess
import wave
from pathlib import Path

_NO_WINDOW = 0x08000000


def _probe_wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        if rate <= 0:
            raise ValueError(f"Invalid WAV framerate in {path}")
        return frames / float(rate)


def _probe_ffprobe_seconds(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    kwargs = {
        "stderr": subprocess.STDOUT,
        "text": True,
    }
    if hasattr(subprocess, "STARTUPINFO"):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = si
        kwargs["creationflags"] = _NO_WINDOW

    out = subprocess.check_output(cmd, **kwargs).strip()
    return float(out)


def probe_audio_duration_seconds(path: Path) -> float:
    ext = path.suffix.lower()
    if ext == ".wav":
        return _probe_wav_seconds(path)

    try:
        return _probe_ffprobe_seconds(path)
    except Exception as e:
        raise RuntimeError(
            f"Cannot probe duration for {path.name}. Install ffprobe (ffmpeg) or use WAV files. Details: {e}"
        ) from e
