# TikTok Setup and Runbook

## 1) Dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

If `playwright` is installed but Chromium is missing, TikTok upload will fail with browser launch errors.

## 2) Environment Variables

Add these values in `.env`:

```env
TIKTOK_ENABLE=1
TIKTOK_PROFILE_DIR=./data/tiktok_profile
TIKTOK_STORAGE_STATE=./data/tiktok_storage_state.json
TIKTOK_HEADLESS=0
TIKTOK_UPLOAD_URL=https://www.tiktok.com/upload
TIKTOK_PUBLISH_TIMEOUT_SEC=180
SANITIZER_FRAME_SAMPLES=20
SANITIZER_SAMPLE_FPS=1
SANITIZER_MAX_MASK_AREA=0.35
```

## 3) First Login (Manual)

Run once to create the persistent TikTok session:

```bash
python -m utils.tiktok_uploader --login
```

Flow:
1. Chromium opens on TikTok login.
2. Login manually (and solve captcha if requested).
3. Return to terminal and press `ENTER`.
4. Session gets stored in:
   - `TIKTOK_PROFILE_DIR`
   - `TIKTOK_STORAGE_STATE`

## 4) Upload CLI

Manual test upload:

```bash
python -m utils.tiktok_uploader --upload --video "C:/path/video.mp4" --caption "Texto #hashtag"
```

If successful, output includes `status=published` and `post_url` when detected.

## 5) Pipeline Integration

Run complete X pipeline with TikTok enabled:

```bash
python scrapping/x/x_action_pipeline.py --user porqueTTarg --links https://twitter.com/i/status/123 --publish-tiktok 1
```

TikTok only mode:

```bash
python scrapping/x/x_action_pipeline.py --user porqueTTarg --links https://twitter.com/i/status/123 --tiktok-only
```

What happens in the pipeline:
1. Extract X videos.
2. Generate captions.
3. Sanitize video (`utils/video_sanitizer.py`):
   - QR detection
   - Static overlay detection
   - ROI-only blur
4. Save intermediate JSON with sanitizer fields: `data/x_videos_sanitized_<user>_<timestamp>.json`.
5. Build reels JSON with sanitized video path.
6. Publish IG (unless `--tiktok-only`).
7. Publish TikTok if enabled.

## 6) Dedup and History

TikTok history file:

```text
data/noticias_publicadas_tiktok.json
```

Dedup key priority:
1. `ig_key` (if available)
2. SHA1 hash of final video file

If key exists in history, item is skipped.

## 7) Sanitizer Outputs

Sanitized videos:

```text
extractor_x/downloads/x_sanitized/
```

Sanitizer reports copied for auditing:

```text
data/sanitizer_reports/
```

Statuses:
- `clean`: no risky overlay found, file copied as sanitized output
- `sanitized`: detections found and ROI blur applied
- `blocked`: detected area too large (`> SANITIZER_MAX_MASK_AREA`), TikTok skip
- `error`: sanitizer failed, TikTok skip

## 8) Troubleshooting

### No TikTok session found
Run:

```bash
python -m utils.tiktok_uploader --login
```

### Upload stuck waiting for Post button
TikTok web UI selectors changed. Check generated debug file:

```text
data/tiktok_upload_debug.html
```

Update selectors in `utils/tiktok_uploader.py`.

### Captcha or security challenge
Automation cannot bypass TikTok anti-bot checks. Complete challenge manually in visible mode (`TIKTOK_HEADLESS=0`) and retry.

### Sanitizer blocks too many videos
Tune:
- `SANITIZER_MAX_MASK_AREA`
- `SANITIZER_FRAME_SAMPLES`
- `SANITIZER_SAMPLE_FPS`

Lower mask strictness only if content quality remains acceptable.
