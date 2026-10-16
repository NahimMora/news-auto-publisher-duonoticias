from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from extractor_x.extractor_x_videos import (
    _extract_tweet_info,
    _fetch_recent_tweet_urls,
    _tweet_id_from_url,
    _tweet_timestamp_from_id,
)
from storage.settings import PipelineSettings, get_settings


class YtDlpXStrategy:
    def __init__(self, settings: PipelineSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.cookies_path = self.settings.base_dir / "scrapping" / "cookies.txt"

    def extract(self, handle: str, limit: int, max_age_hours: int) -> List[Dict[str, Any]]:
        handle = self._normalize_handle(handle)
        if not handle:
            return []
        cookies = str(self.cookies_path) if self.cookies_path.exists() else None
        max_age_seconds = max_age_hours * 3600
        try:
            url_multiplier = max(1, int(os.getenv("X_YTDLP_URL_MULTIPLIER", "6")))
            tweet_urls = _fetch_recent_tweet_urls(
                handle,
                max_items=max(limit * url_multiplier, limit),
                cookies_path=cookies,
                max_age_seconds=max_age_seconds,
            )
        except Exception:
            return []

        results: List[Dict[str, Any]] = []
        seen_ids = set()
        now_ts = int(time.time())
        seen_urls = set()

        for tweet_url in tweet_urls:
            if len(results) >= limit:
                break
            if "/status/" not in tweet_url:
                continue
            normalized_url = str(tweet_url).strip()
            if not normalized_url or normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            tweet_id_from_url = _tweet_id_from_url(normalized_url)
            tweet_ts = _tweet_timestamp_from_id(tweet_id_from_url or "")
            if tweet_ts and (now_ts - tweet_ts) > max_age_seconds:
                continue
            info = _extract_tweet_info(tweet_url, cookies=cookies, retry=1)
            parsed = self._parse_info(info, tweet_url=tweet_url)
            if not parsed:
                continue
            tweet_id = str(parsed.get("tweet_id") or "").strip()
            if not tweet_id or tweet_id in seen_ids:
                continue
            timestamp = int(parsed.get("timestamp") or 0)
            if timestamp and (now_ts - timestamp) > max_age_seconds:
                continue
            seen_ids.add(tweet_id)
            results.append(parsed)

        results.sort(key=lambda row: int(row.get("timestamp") or 0), reverse=True)
        return results[:limit]

    def _parse_info(self, info: Dict[str, Any], *, tweet_url: str) -> Optional[Dict[str, Any]]:
        if not info:
            return None
        media_url = self._best_video_url(info)
        if not media_url:
            return None
        return {
            "tweet_id": str(info.get("id") or ""),
            "tweet_url": str(info.get("webpage_url") or info.get("original_url") or tweet_url),
            "author": str(info.get("uploader") or info.get("channel") or ""),
            "handle": str(info.get("uploader_id") or ""),
            "original_text": str(info.get("description") or info.get("title") or ""),
            "timestamp": int(info.get("timestamp") or 0),
            "duration_seconds": float(info.get("duration") or 0.0),
            "visible_metrics": {
                "likes": float(info.get("like_count") or 0),
                "comments": float(info.get("comment_count") or 0),
                "shares": float(info.get("repost_count") or 0),
                "views": float(info.get("view_count") or 0),
            },
            "media": [
                {
                    "type": "video",
                    "media_key": "",
                    "url": media_url,
                    "thumbnail_url": str((info.get("thumbnail") or "")),
                }
            ],
            "raw_payload": info,
        }

    @staticmethod
    def _best_video_url(info: Dict[str, Any]) -> Optional[str]:
        formats = info.get("formats") or []
        candidates = [
            item
            for item in formats
            if item.get("ext") == "mp4" and item.get("url")
        ]
        if not candidates:
            url = str(info.get("url") or "").strip()
            return url or None
        candidates.sort(key=lambda item: ((item.get("height") or 0), (item.get("tbr") or 0)), reverse=True)
        return str(candidates[0].get("url") or "")

    @staticmethod
    def _normalize_handle(value: str) -> str:
        raw = (value or "").strip()
        if not raw:
            return ""
        if raw.startswith(("http://", "https://")):
            raw = (urlparse(raw).path or "").strip("/")
        raw = raw.replace("x.com/", "").replace("twitter.com/", "").strip("/")
        if "/" in raw:
            raw = raw.split("/", 1)[0]
        return raw.lstrip("@").strip()
