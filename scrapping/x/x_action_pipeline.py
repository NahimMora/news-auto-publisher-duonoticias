"""Run X pipeline: fetch videos -> sanitize -> build reels -> publish IG and optional TikTok."""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

DATA_DIR = BASE_DIR / "data"
EXTRACTOR_DIR = BASE_DIR / "extractor_x"
SANITIZED_DIR = EXTRACTOR_DIR / "downloads" / "x_sanitized"
SANITIZER_REPORT_DIR = DATA_DIR / "sanitizer_reports"
TIKTOK_HISTORY_PATH = DATA_DIR / "noticias_publicadas_tiktok.json"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv(BASE_DIR / ".env")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value: {value}")


def _latest_extractor_file() -> Optional[Path]:
    files = list(EXTRACTOR_DIR.glob("results_*.json"))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _latest_ai_file() -> Optional[Path]:
    files = list(DATA_DIR.glob("x_videos_ai_*.json"))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _load_rows(path: Path) -> List[Dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_command(cmd: List[str], label: str) -> bool:
    logging.info("Running %s", label)
    code = subprocess.call(cmd, cwd=str(BASE_DIR))
    if code != 0:
        logging.error("%s failed with code %s", label, code)
        return False
    return True


def _sanitize_items(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from utils.video_sanitizer import SanitizerConfig, sanitize_video

    cfg = SanitizerConfig.from_env()
    SANITIZED_DIR.mkdir(parents=True, exist_ok=True)
    SANITIZER_REPORT_DIR.mkdir(parents=True, exist_ok=True)

    updated: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        raw_path = item.get("video_path") or item.get("file")
        if not raw_path:
            updated.append(item)
            continue

        src = Path(raw_path)
        if not src.exists():
            updated.append(item)
            continue

        logging.info("Sanitizing %s", src.name)
        report = sanitize_video(str(src), SANITIZED_DIR, cfg=cfg)
        report_file = Path(str(report.get("report_path") or ""))
        if report_file.exists():
            report_copy = SANITIZER_REPORT_DIR / report_file.name
            try:
                shutil.copy2(report_file, report_copy)
                report["report_path"] = str(report_copy)
            except Exception:
                report["report_path"] = str(report_file)

        status = str(report.get("status") or "error")
        item["sanitizer_status"] = status
        item["sanitizer_report"] = report.get("report_path")
        item["sanitizer_detections"] = report.get("detections") or []

        if status in {"sanitized", "clean"}:
            output = str(report.get("output") or "").strip()
            if output and Path(output).exists():
                item["video_path"] = output
                item["file"] = output
                item["skip_tiktok"] = False
        elif status == "blocked":
            item["skip_tiktok"] = True
            item["skip_tiktok_reason"] = "sanitizer_blocked"
        else:
            item["skip_tiktok"] = True
            item["skip_tiktok_reason"] = "sanitizer_error"

        updated.append(item)

    return updated


def _build_reels_items(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    rows_sorted = sorted(rows, key=lambda x: int(x.get("timestamp") or 0), reverse=True)

    for item in rows_sorted:
        tweet_id = str(item.get("tweet_id") or item.get("id") or "").strip()
        if not tweet_id:
            continue

        timestamp = item.get("timestamp")
        if not isinstance(timestamp, (int, float)):
            continue

        file_path = item.get("video_path") or item.get("file")
        if not file_path or not Path(file_path).exists():
            continue

        tweet_url = item.get("tweet_url") or item.get("url") or f"https://twitter.com/i/status/{tweet_id}"
        caption = (item.get("texto_instagram") or item.get("original_text") or "").strip()
        title = (item.get("titulo_instagram") or item.get("title") or "").strip()
        ig_key = sha1(tweet_id.encode("utf-8")).hexdigest()

        reels_item: Dict[str, Any] = {
            "titulo": title[:80] if title else "",
            "texto_instagram": caption or "Video",
            "videos_locales": [str(file_path)],
            "source_url": tweet_url,
            "ig_key": ig_key,
            "sanitizer_status": item.get("sanitizer_status"),
            "sanitizer_report": item.get("sanitizer_report"),
            "skip_tiktok": bool(item.get("skip_tiktok")),
        }
        if item.get("skip_tiktok_reason"):
            reels_item["skip_tiktok_reason"] = item.get("skip_tiktok_reason")

        items.append(reels_item)

    return items


def _write_reels_file(items: List[Dict[str, Any]], user: str) -> Optional[Path]:
    if not items:
        return None
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    out_path = DATA_DIR / f"x_reels_{user}_{stamp}.json"
    _write_json(out_path, items)
    return out_path


def _write_sanitized_intermediate(items: List[Dict[str, Any]], user: str) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    out_path = DATA_DIR / f"x_videos_sanitized_{user}_{stamp}.json"
    _write_json(out_path, items)
    return out_path


def _publish_tiktok(reels_file: Path, max_items: Optional[int] = None) -> None:
    from utils.tiktok_history import append_tiktok_history, build_tiktok_key, history_keys, load_tiktok_history
    from utils.tiktok_uploader import TikTokUploader, TikTokUploaderConfig

    rows = _load_rows(reels_file)
    if not rows:
        logging.info("No TikTok items to publish")
        return

    cfg = TikTokUploaderConfig.from_env()
    if not cfg.storage_state.exists() and (not cfg.profile_dir.exists() or not any(cfg.profile_dir.iterdir())):
        logging.warning(
            "TikTok session not found. Run: python -m utils.tiktok_uploader --login"
        )
        return

    uploader = TikTokUploader(cfg, logger=logging.getLogger("tiktok"))
    history = load_tiktok_history(TIKTOK_HISTORY_PATH)
    published_keys = history_keys(history)

    posted = 0
    for item in rows:
        if max_items is not None and posted >= max_items:
            break

        if item.get("skip_tiktok"):
            logging.info("TikTok skip (blocked): %s", item.get("source_url") or item.get("ig_key"))
            continue

        video_paths = [v for v in (item.get("videos_locales") or []) if v]
        if not video_paths:
            continue
        video_path = str(video_paths[0])
        if not Path(video_path).exists():
            logging.warning("TikTok skip missing file: %s", video_path)
            continue

        key = build_tiktok_key(item, video_path)
        if key in published_keys:
            logging.info("TikTok skip dedup key: %s", key)
            continue

        caption = (item.get("texto_instagram") or item.get("caption") or "").strip()
        result = uploader.upload(video_path, caption)
        if result.get("status") != "published":
            logging.error("TikTok upload failed for %s: %s", key, result)
            continue

        append_tiktok_history(
            TIKTOK_HISTORY_PATH,
            key=key,
            video=video_path,
            caption=caption,
            post_url=str(result.get("post_url") or ""),
            extra={
                "ig_key": item.get("ig_key") or "",
                "source_url": item.get("source_url") or "",
                "published_at_local": datetime.now(timezone.utc).astimezone().isoformat(),
            },
        )
        published_keys.add(key)
        posted += 1
        logging.info("TikTok published key=%s", key)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="X -> IG/TikTok Reels pipeline.")
    parser.add_argument("--user", required=True, help="X username (without @)")
    parser.add_argument("--links", nargs="*", help="Lista de URLs de tweets (X)")
    parser.add_argument("--limit", type=int, default=15, help="Max videos to fetch")
    parser.add_argument("--max-age-hours", type=int, default=24, help="Max age for videos")
    parser.add_argument("--cookies", default=str(BASE_DIR / "scrapping" / "cookies.txt"), help="cookies.txt path")
    parser.add_argument(
        "--publish-tiktok",
        nargs="?",
        const=True,
        default=None,
        type=_parse_bool,
        help="Enable TikTok publish (true/false). Defaults to TIKTOK_ENABLE.",
    )
    parser.add_argument("--tiktok-only", action="store_true", help="Skip IG publishing and publish TikTok only")
    parser.add_argument("--max-tiktok", type=int, default=None, help="Max TikTok posts to publish")
    return parser.parse_args()


def main() -> None:
    _setup_logging()
    args = _parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    links = [link for link in (args.links or []) if link]
    if not links:
        logging.error("Scrapping disabled: provide X links via --links")
        return

    extractor_cmd = [
        sys.executable,
        "extractor_x/extractor_x_videos.py",
        *links,
        "--max-videos",
        str(args.limit),
        "--max-age-hours",
        str(args.max_age_hours),
        "--cookies",
        args.cookies,
    ]
    if not _run_command(extractor_cmd, "extractor_x"):
        return

    latest = _latest_extractor_file()
    if not latest:
        logging.error("No extractor results found")
        return

    ai_cmd = [
        sys.executable,
        "utils/x_captioner_openai.py",
        "--input",
        str(latest),
    ]
    if not _run_command(ai_cmd, "x_captioner_openai"):
        return

    ai_latest = _latest_ai_file()
    source = ai_latest if ai_latest else latest
    if ai_latest:
        logging.info("Using AI metadata file: %s", ai_latest)
    else:
        logging.info("No AI file detected. Using extractor metadata")

    source_rows = _load_rows(source)
    if not source_rows:
        logging.error("No rows available in %s", source)
        return

    sanitized_rows = _sanitize_items(source_rows)
    sanitized_intermediate = _write_sanitized_intermediate(sanitized_rows, args.user)
    logging.info("Sanitized intermediate written: %s", sanitized_intermediate)

    reels_items = _build_reels_items(sanitized_rows)
    reels_file = _write_reels_file(reels_items, args.user)
    if not reels_file:
        logging.info("No items to publish")
        return

    publish_tiktok = (
        args.publish_tiktok
        if args.publish_tiktok is not None
        else os.getenv("TIKTOK_ENABLE", "0") == "1"
    )
    if args.tiktok_only:
        publish_tiktok = True

    if not args.tiktok_only:
        publish_cmd = [
            sys.executable,
            "utils/instagram_reels_only.py",
            "--file",
            str(reels_file),
        ]
        _run_command(publish_cmd, "instagram_reels_only")

    if publish_tiktok:
        _publish_tiktok(reels_file, max_items=args.max_tiktok)


if __name__ == "__main__":
    main()
