"""Stub subtitle helpers (use FFmpeg drawtext/subtitles instead)."""
from typing import List, Optional


def get_subtitle_segments(*args, **kwargs) -> List[dict]:
    return []


def is_title_active(title_cfg: Optional[dict], time_sec: float) -> bool:
    if not title_cfg:
        return False
    start = float(title_cfg.get("start", 0))
    end = float(title_cfg.get("end", 0))
    return start <= time_sec <= end


def render_title(frame, title_cfg, time_sec):
    return frame


def render_subtitles(frame, subtitle_segments, time_sec, subtitle_style=None):
    return frame
