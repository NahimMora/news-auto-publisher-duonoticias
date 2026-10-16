"""Pipeline: get tweet URLs, dedup, download via yt-dlp."""
import argparse
import json
import re
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from yt_dlp import YoutubeDL

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
DOWNLOAD_DIR = DATA_DIR / "x_videos_downloads"
HISTORY_PATH = DATA_DIR / "x_videos_history.json"


def _load_history() -> set[str]:
    if HISTORY_PATH.exists():
        try:
            data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return set(str(x) for x in data)
        except Exception:
            pass
    return set()


def _save_history(items: set[str]) -> None:
    HISTORY_PATH.write_text(json.dumps(sorted(items), ensure_ascii=False, indent=2), encoding="utf-8")


def _load_cookies(path: Optional[str]) -> httpx.Cookies:
    jar = httpx.Cookies()
    if not path:
        return jar
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return jar
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _, cookie_path, _, _, name, value = parts[:7]
        jar.set(name, value, domain=domain, path=cookie_path)
    return jar


def _fetch_tweet_urls(username: str, limit: int, cookies_path: Optional[str]) -> List[str]:
    headers = {"User-Agent": "Mozilla/5.0"}
    ids: List[str] = []

    # 1) Try public syndication endpoint (no JS)
    syndication_urls = [
        f"https://cdn.syndication.twimg.com/srv/timeline-profile/screen-name/{username}",
        f"https://cdn.syndication.twimg.com/timeline/profile?screen_name={username}",
    ]
    with httpx.Client(timeout=25.0, headers=headers, follow_redirects=True) as client:
        for url in syndication_urls:
            for prefix in ("", "https://r.jina.ai/http://"):
                try:
                    resp = client.get(f"{prefix}{url}")
                except Exception:
                    continue
                if resp.status_code != 200 or not resp.text:
                    continue
                ids = (
                    re.findall(r'\"tweet_id\":\"(\d+)\"', resp.text)
                    or re.findall(r'\"id_str\":\"(\d+)\"', resp.text)
                    or re.findall(r"/status/(\d+)", resp.text)
                )
                if ids:
                    break
            if ids:
                break

    # 2) Fallback to authenticated /media HTML
    if not ids:
        cookies = _load_cookies(cookies_path)
        url = f"https://x.com/{username}/media"
        with httpx.Client(timeout=20.0, headers=headers, cookies=cookies, follow_redirects=True) as client:
            resp = client.get(url)
            if resp.status_code == 200 and resp.text:
                ids = re.findall(rf'/{re.escape(username)}/status/(\\d+)', resp.text)

    # sort newest -> oldest by tweet id (roughly time-ordered)
    ids_sorted = sorted({int(t) for t in ids}, reverse=True)
    seen: List[str] = []
    for tid in ids_sorted:
        tweet_url = f"https://twitter.com/{username}/status/{tid}"
        if tweet_url not in seen:
            seen.append(tweet_url)
    return seen[:limit]


class _QuietLogger:
    def debug(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        pass

    def error(self, msg: str) -> None:
        pass


def _extract_info(tweet_url: str, cookies_path: Optional[str]) -> Dict[str, Any]:
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "no_warnings": True,
        "noplaylist": True,
        "ignoreerrors": True,
        "noprogress": True,
        "logger": _QuietLogger(),
    }
    if cookies_path:
        ydl_opts["cookies"] = cookies_path
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(tweet_url, download=False)
    return info or {}


def _download(tweet_url: str, cookies_path: Optional[str], output_dir: Path) -> Optional[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "ignoreerrors": True,
        "noprogress": True,
        "logger": _QuietLogger(),
    }
    if cookies_path:
        ydl_opts["cookies"] = cookies_path
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(tweet_url, download=True)
        if not info:
            return None
        vid = info.get("id")
        if not vid:
            return None
        candidate = output_dir / f"{vid}.mp4"
        if candidate.exists():
            return str(candidate)
    return None


def _tweet_id_from_url(url: str) -> Optional[int]:
    match = re.search(r"/status/(\\d+)", url)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _tweet_date_yyyymmdd(tweet_id: int) -> Optional[str]:
    # Twitter snowflake: timestamp is ms since 2010-11-04
    try:
        timestamp_ms = (tweet_id >> 22) + 1288834974657
        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).astimezone()
        return dt.strftime("%Y%m%d")
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="X video pipeline via yt-dlp (no Selenium).")
    parser.add_argument("--user", required=True, help="X username (without @)")
    parser.add_argument("--limit", type=int, default=15, help="Max videos to fetch")
    parser.add_argument("--cookies", default=str(BASE_DIR / "scrapping" / "cookies.txt"), help="cookies.txt path")
    parser.add_argument("--ignore-history", action="store_true", help="Ignore history and reprocess old tweets")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    history = _load_history()
    # pull a limited number of newest candidates, stop after first N videos
    candidate_count = max(args.limit * 8, 60)
    tweet_urls = _fetch_tweet_urls(args.user, candidate_count, args.cookies)
    if not tweet_urls:
        print("No se encontraron tweets en /media (login/cookies requeridos)")
        return

    if args.ignore_history:
        new_urls = tweet_urls
    else:
        new_urls = [u for u in tweet_urls if u not in history]

    results: List[Dict[str, Any]] = []
    today_str = datetime.now().strftime("%Y%m%d")
    for tweet_url in new_urls:
        if len(results) >= args.limit:
            break
        tweet_id = _tweet_id_from_url(tweet_url)
        tweet_date = _tweet_date_yyyymmdd(tweet_id) if tweet_id else None
        if tweet_date and tweet_date != today_str:
            continue
        try:
            info = _extract_info(tweet_url, args.cookies)
        except Exception:
            info = {}
        formats = info.get("formats") or []
        has_video = any(f.get("ext") == "mp4" for f in formats) or bool(info.get("duration"))
        if not has_video:
            continue
        upload_date = info.get("upload_date")
        if upload_date and upload_date != today_str:
            continue
        desc = (info.get("description") or info.get("title") or "").strip()
        try:
            downloaded_path = _download(tweet_url, args.cookies, DOWNLOAD_DIR)
        except Exception:
            downloaded_path = None
        if not downloaded_path:
            continue
        results.append(
            {
                "tweet_url": tweet_url,
                "description": desc,
                "id": info.get("id"),
                "uploader": info.get("uploader"),
                "upload_date": upload_date,
                "file": downloaded_path,
                "downloaded_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        history.add(tweet_url)

    _save_history(history)

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    out_path = DATA_DIR / f"x_videos_{args.user}_{stamp}.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"OK: {len(results)} items")
    print(f"Output: {out_path}")
    print(f"Downloads: {DOWNLOAD_DIR}")


if __name__ == "__main__":
    main()
