"""Recorte mecanico y predecible del video original.

Sin transcripcion, sin analisis de audio, sin highlights ni seleccion semantica:

- hasta ``clip_seconds`` (60 s): se usa el video completo;
- mas largo: tramos cronologicos desde el inicio, 0-60 y 60-120 (el segundo con
  lo que quede si dura menos de 120 s). Nunca se buscan otros fragmentos.
- un segundo tramo mas corto que ``min_clip_seconds`` no se publica.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass(frozen=True)
class ClipSpec:
    index: int
    start: float
    duration: float

    @property
    def end(self) -> float:
        return self.start + self.duration


def plan_clips(duration: float, *, clip_seconds: float = 60.0, max_clips: int = 2, min_clip_seconds: float = 5.0) -> List[ClipSpec]:
    total = max(0.0, float(duration or 0.0))
    if total <= 0:
        return []
    if total <= clip_seconds:
        return [ClipSpec(0, 0.0, round(total, 2))]
    clips: List[ClipSpec] = []
    start = 0.0
    while len(clips) < max_clips and start < total:
        length = min(clip_seconds, total - start)
        if clips and length < min_clip_seconds:
            break
        clips.append(ClipSpec(len(clips), round(start, 2), round(length, 2)))
        start += clip_seconds
    return clips


def cut_segment(source: str, output: str, clip: ClipSpec, *, ffmpeg: str = "ffmpeg", timeout: int = 300) -> str:
    """Corte exacto (re-encode) del tramo; mantiene el audio original."""
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg, "-v", "error", "-y",
        "-ss", f"{clip.start:.2f}", "-i", str(source), "-t", f"{clip.duration:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(output),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0 or not Path(output).exists():
        raise RuntimeError(f"corte de video fallido: {(result.stderr or '').strip()[-300:]}")
    return str(output)
