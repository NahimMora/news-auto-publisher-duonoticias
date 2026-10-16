"""Deprecated wrapper for video processing using FFmpeg pipeline."""
from utils.video_processor import process_video_for_instagram


def process_video(
    input_path,
    output_path,
    template_path=None,
    enable_subtitles=True,
    progress_cb=None,
    quality="normal",
    title_text=None,
    output_mode=None,
):
    if progress_cb:
        try:
            progress_cb({"stage": "init", "message": "Starting", "progress": 0})
        except Exception:
            pass
    result = process_video_for_instagram(
        input_path,
        output_path,
        template_path=template_path,
        enable_subtitles=enable_subtitles,
        quality=quality,
        title_text=title_text,
        output_mode=output_mode,
    )
    if progress_cb:
        try:
            progress_cb({"stage": "done", "message": "Completed", "progress": 100})
        except Exception:
            pass
    return result
