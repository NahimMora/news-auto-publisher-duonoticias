"""Minimal overlay template loader (FFmpeg pipeline handles overlays)."""
import json
from pathlib import Path


def load_template(path):
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def apply_overlays(frame, overlays, time_sec):
    return frame
