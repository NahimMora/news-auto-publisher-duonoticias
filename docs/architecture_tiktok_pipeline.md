# TikTok Pipeline Architecture

## Flow Diagram (Text)

```text
scrapping/x/x_action_pipeline.py
  -> extractor_x/extractor_x_videos.py
  -> utils/x_captioner_openai.py
  -> utils/video_sanitizer.py (per video)
       - sample frames
       - detect QR
       - detect static overlays
       - blur only detected ROIs via ffmpeg mask + maskedmerge
       - classify: clean | sanitized | blocked | error
  -> data/x_videos_sanitized_<user>_<ts>.json
  -> data/x_reels_<user>_<ts>.json
  -> IG branch (existing): utils/instagram_reels_only.py
  -> TikTok branch (optional): utils/tiktok_uploader.py
       - Playwright persistent session
       - upload + caption + post
  -> data/noticias_publicadas_tiktok.json (dedup history)
```

## Main Modules

- `utils/video_sanitizer.py`
  - `sample_frames(video_path, sample_fps, max_frames)`
  - `detect_qr(frames)`
  - `detect_static_overlays(frames)`
  - `merge_bboxes(detections, iou_threshold=0.2)`
  - `build_mask(width, height, detections)`
  - `apply_blur_ffmpeg(input_path, mask_path, output_path)`
  - `sanitize_video(input_path, output_dir, cfg)`

- `utils/tiktok_uploader.py`
  - `TikTokUploaderConfig.from_env()`
  - `TikTokUploader.login()`
  - `TikTokUploader.upload(video_path, caption)`
  - Persistent profile and `storage_state` backup

- `utils/tiktok_history.py`
  - `build_tiktok_key(item, video_path)`
  - `load_tiktok_history(path)`
  - `append_tiktok_history(...)`
  - Dedup by `ig_key` or SHA1(video)

## Integration Points

`x_action_pipeline.py` was extended in these points:

1. Sanitizer stage before reels build.
2. Reels JSON enriched with:
   - `sanitizer_status`
   - `sanitizer_report`
   - `skip_tiktok`
   - `skip_tiktok_reason` (if blocked/error)
3. New CLI flags:
   - `--publish-tiktok true|false`
   - `--tiktok-only`
   - `--max-tiktok`
4. Optional TikTok branch with dedup + history.
5. IG branch kept as-is unless `--tiktok-only`.

## Extension Points

1. Detection heuristics (`utils/video_sanitizer.py`)
   - tune variance percentile
   - tune morphology kernels
   - add low-cost text-band detector

2. TikTok selectors (`utils/tiktok_uploader.py`)
   - update selector list when web UI changes
   - add locale-specific selectors

3. Publish policy (`x_action_pipeline.py`)
   - custom skip rules
   - priority queues by source/user
   - retries per item

4. History metadata (`utils/tiktok_history.py`)
   - add account ID
   - add sanitizer report snapshot
   - add moderation tags

## Operational Guarantees

- Raw X videos are sanitized before downstream publishing.
- `blocked` sanitizer status never attempts TikTok publish.
- TikTok reposts are skipped via persistent history key set.
- Instagram flow remains available and unchanged by default.
