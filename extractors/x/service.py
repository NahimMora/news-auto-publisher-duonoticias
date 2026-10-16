from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Sequence
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

from extractor_x.extractor_x_videos import _extract_tweet_info
from extractor_x.extractor_x_videos import _tweet_timestamp_from_id
from extractors.x.playwright_strategy import PlaywrightAuthenticatedXStrategy
from extractors.x.yt_dlp_strategy import YtDlpXStrategy
from storage.media_hash import file_sha1, perceptual_hash_for_asset
from storage.models import Asset, ExtractedContent
from storage.settings import PipelineSettings, get_settings
from utils.http_client import download_to_file


class XExtractionService:
    def __init__(self, settings: PipelineSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.playwright_strategy = PlaywrightAuthenticatedXStrategy(self.settings)
        self.ytdlp_strategy = YtDlpXStrategy(self.settings)
        self.download_dir = self.settings.data_dir / "pipeline_x_raw"
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def extract(
        self,
        *,
        handles: Sequence[str] | None = None,
        limit_per_handle: int = 5,
        max_age_hours: int = 24,
    ) -> List[ExtractedContent]:
        mode = (self.settings.x_mode or "manual").lower().strip()
        if mode == "manual":
            return []
        final_items: List[ExtractedContent] = []
        seen_handles = set()
        for handle in (handles or self.settings.x_sources):
            handle = self._normalize_handle(str(handle or ""))
            if not handle:
                continue
            if handle in seen_handles:
                continue
            seen_handles.add(handle)
            rows: List[Dict[str, object]] = []
            strategy = "none"
            if mode == "api":
                rows = self._extract_via_api(handle, limit_per_handle, max_age_hours)
                strategy = "x_api"
            if not rows and mode == "feed":
                rows = self.playwright_strategy.extract(handle, limit_per_handle, max_age_hours)
                strategy = "playwright_home" if handle.lower() == "home" else "playwright_media_feed"
            if not rows and mode == "browser":
                rows = self.playwright_strategy.extract(handle, limit_per_handle, max_age_hours)
                strategy = "playwright_home" if handle.lower() == "home" else "playwright"
            if not rows:
                rows = self.ytdlp_strategy.extract(handle, limit_per_handle, max_age_hours)
                strategy = "yt-dlp"
            rows = self._filter_recent_rows(rows, max_age_hours=max_age_hours)
            for row in rows:
                author_handle = self._normalize_handle(str(row.get("handle") or "")) or handle
                scan_scope = "home_timeline" if handle.lower() == "home" else "configured_handles_media_feed"
                content = self._to_content(
                    row,
                    handle=author_handle,
                    strategy=strategy,
                    scan_scope=scan_scope,
                    requested_handle=handle,
                )
                final_items.append(content)
        final_items.sort(
            key=lambda item: float((item.ranking_signals or {}).get("tweet_timestamp") or 0),
            reverse=True,
        )
        return final_items

    def import_url(self, url: str, *, dry_run: bool = False) -> ExtractedContent:
        tweet_url = self._normalize_tweet_url(url)
        tweet_id = self._tweet_id_from_url(tweet_url)
        parsed: Dict[str, object] | None = None
        if not dry_run and tweet_id and "mock" not in tweet_url.lower():
            cookies = str(self.ytdlp_strategy.cookies_path) if self.ytdlp_strategy.cookies_path.exists() else None
            try:
                info = _extract_tweet_info(tweet_url, cookies=cookies, retry=1)
                parsed = self.ytdlp_strategy._parse_info(info, tweet_url=tweet_url)
            except Exception:
                parsed = None
        if not parsed:
            is_mock = "mock" in tweet_url.lower()
            local_video = self._fixture_video_path(tweet_id)
            parsed = {
                "tweet_id": tweet_id,
                "tweet_url": tweet_url,
                "author": "",
                "handle": self._handle_from_url(tweet_url),
                "original_text": (
                    "Video politico de X con una escena de seguridad que genero debate y sorpresa."
                    if is_mock else "URL importada de X para analisis manual."
                ),
                "timestamp": 0,
                "duration_seconds": 18.0 if is_mock and local_video else 0.0,
                "visible_metrics": (
                    {"views": 250000, "likes": 12000, "replies": 900, "reposts": 1800, "bookmarks": 400}
                    if is_mock else {}
                ),
                "local_video_path": local_video,
                "media": [
                    {
                        "type": "video",
                        "media_key": "",
                        "url": "",
                        "thumbnail_url": "",
                    }
                ],
                "raw_payload": {"imported_url": tweet_url, "dry_run": dry_run, "resolver": "manual_fallback"},
            }
        handle = self._normalize_handle(str(parsed.get("handle") or self._handle_from_url(tweet_url) or "manual"))
        return self._to_content(parsed, handle=handle or "manual", strategy="manual_url")

    def _to_content(
        self,
        row: Dict[str, object],
        *,
        handle: str,
        strategy: str,
        scan_scope: str = "configured_handles_media_feed",
        requested_handle: str = "",
    ) -> ExtractedContent:
        media = (row.get("media") or [])
        primary = media[0] if media else {}
        video_url = str(primary.get("url") or "").strip()
        local_path = str(row.get("local_video_path") or "").strip()
        if not local_path and video_url and Path(video_url).exists():
            local_path = video_url
            video_url = ""
        if not local_path and video_url:
            local_path = self._download_video(str(row.get("tweet_id") or ""), video_url)
        thumbnail_url = str(primary.get("thumbnail_url") or "").strip()
        perceptual_hash = ""
        sha1 = ""
        if local_path:
            sha1 = file_sha1(local_path)
            try:
                perceptual_hash = perceptual_hash_for_asset(local_path, "video") or ""
            except Exception:
                perceptual_hash = ""
        asset = Asset(
            kind="video",
            path=local_path,
            remote_url=video_url,
            duration_seconds=float(row.get("duration_seconds") or 0.0),
            sha1=sha1,
            perceptual_hash=perceptual_hash,
            meta={"thumbnail_url": thumbnail_url},
        )
        raw_text = self._strip_urls(str(row.get("original_text") or "").strip())
        timestamp = self._timestamp_seconds(row.get("timestamp"))
        return ExtractedContent(
            source="x",
            source_type="x_video",
            source_item_id=str(row.get("tweet_id") or ""),
            canonical_url=str(row.get("tweet_url") or ""),
            author=str(row.get("author") or "").strip(),
            source_handle=handle,
            title=self._build_title(raw_text),
            summary=raw_text[:280],
            body_text=raw_text,
            media_type="video",
            created_at=self._created_at_iso(timestamp),
            visible_metrics=dict(row.get("visible_metrics") or {}),
            tags=["x", handle],
            ranking_signals={
                "duration_seconds": float(row.get("duration_seconds") or 0.0),
                "strategy": strategy,
                "x_mode": self.settings.x_mode,
                "x_scan_scope": scan_scope,
                "requested_handle": requested_handle or handle,
                "tweet_timestamp": timestamp,
                "age_hours": self._age_hours(timestamp),
            },
            raw_payload=dict(row.get("raw_payload") or row),
            assets=[asset],
        )

    def _download_video(self, tweet_id: str, video_url: str) -> str:
        if not tweet_id or not video_url:
            return ""
        output_path = self.download_dir / f"{tweet_id}.mp4"
        if output_path.exists():
            return str(output_path)
        try:
            download_to_file(video_url, str(output_path), timeout=90.0, retries=3)
            return str(output_path)
        except Exception:
            return ""

    def _fixture_video_path(self, tweet_id: str) -> str:
        manual_dir = self.settings.data_dir / "manual_x_reels"
        if not manual_dir.exists():
            return ""
        exact = manual_dir / f"{tweet_id}_reel.mp4"
        if exact.exists():
            return str(exact)
        if tweet_id.startswith("mock"):
            first = next(iter(sorted(manual_dir.glob("*_reel.mp4"))), None)
            return str(first) if first else ""
        return ""

    @classmethod
    def _normalize_tweet_url(cls, value: str) -> str:
        raw = (value or "").strip()
        if not raw or raw.upper() == "MOCK_URL":
            return "https://x.com/mock/status/mock"
        if raw.startswith("x.com/"):
            raw = "https://" + raw
        if raw.startswith("twitter.com/"):
            raw = "https://" + raw
        return raw

    @staticmethod
    def _tweet_id_from_url(url: str) -> str:
        match = re.search(r"/status/([^/?#]+)", url or "")
        if match:
            return re.sub(r"\W+", "", match.group(1))[:40] or "manual"
        digest = hashlib.sha1((url or "manual").encode("utf-8")).hexdigest()
        return f"manual_{digest[:12]}"

    @staticmethod
    def _handle_from_url(url: str) -> str:
        try:
            parts = [part for part in (urlparse(url).path or "").split("/") if part]
        except Exception:
            return "manual"
        if parts:
            return parts[0].lstrip("@")
        return "manual"

    def _extract_via_api(self, handle: str, limit_per_handle: int, max_age_hours: int) -> List[Dict[str, object]]:
        token = os.getenv("X_BEARER_TOKEN", "").strip()
        if not token:
            return []
        headers = {"Authorization": f"Bearer {token}"}
        base = "https://api.twitter.com/2"
        try:
            with httpx.Client(timeout=20.0, headers=headers) as client:
                user_response = client.get(
                    f"{base}/users/by/username/{handle}",
                    params={"user.fields": "username,name"},
                )
                user_response.raise_for_status()
                user_id = str((user_response.json().get("data") or {}).get("id") or "")
                if not user_id:
                    return []
                tweets_response = client.get(
                    f"{base}/users/{user_id}/tweets",
                    params={
                        "max_results": max(5, min(100, int(limit_per_handle))),
                        "tweet.fields": "created_at,public_metrics,text,attachments",
                        "expansions": "attachments.media_keys",
                        "media.fields": "duration_ms,preview_image_url,type,url,variants",
                    },
                )
                tweets_response.raise_for_status()
                payload = tweets_response.json()
        except Exception:
            return []

        media_by_key = {
            str(item.get("media_key") or ""): item
            for item in (payload.get("includes") or {}).get("media", [])
            if isinstance(item, dict)
        }
        rows: List[Dict[str, object]] = []
        for tweet in payload.get("data") or []:
            if not isinstance(tweet, dict):
                continue
            keys = ((tweet.get("attachments") or {}).get("media_keys") or [])
            media_items = [media_by_key.get(str(key)) for key in keys]
            video = next((item for item in media_items if isinstance(item, dict) and item.get("type") == "video"), None)
            if not video:
                continue
            video_url = self._best_api_video_url(video)
            if not video_url:
                continue
            metrics = dict(tweet.get("public_metrics") or {})
            tweet_id = str(tweet.get("id") or "")
            rows.append(
                {
                    "tweet_id": tweet_id,
                    "tweet_url": f"https://x.com/{handle}/status/{tweet_id}",
                    "author": handle,
                    "handle": handle,
                    "original_text": str(tweet.get("text") or ""),
                    "timestamp": str(tweet.get("created_at") or ""),
                    "duration_seconds": float(video.get("duration_ms") or 0) / 1000.0,
                    "visible_metrics": {
                        "views": metrics.get("impression_count", 0),
                        "likes": metrics.get("like_count", 0),
                        "replies": metrics.get("reply_count", 0),
                        "reposts": metrics.get("retweet_count", 0) + metrics.get("quote_count", 0),
                    },
                    "media": [
                        {
                            "type": "video",
                            "media_key": str(video.get("media_key") or ""),
                            "url": video_url,
                            "thumbnail_url": str(video.get("preview_image_url") or ""),
                        }
                    ],
                    "raw_payload": {"api_tweet": tweet, "api_media": video, "max_age_hours": max_age_hours},
                }
            )
            if len(rows) >= limit_per_handle:
                break
        rows.sort(key=lambda row: self._timestamp_seconds(row.get("timestamp")), reverse=True)
        return rows[:limit_per_handle]

    def _filter_recent_rows(
        self,
        rows: Sequence[Dict[str, object]],
        *,
        max_age_hours: int,
    ) -> List[Dict[str, object]]:
        now_ts = datetime.now(timezone.utc).timestamp()
        max_age_seconds = max_age_hours * 3600
        zone = ZoneInfo(self.settings.timezone)
        filtered: List[Dict[str, object]] = []
        seen_ids = set()
        for row in rows:
            tweet_id = str(row.get("tweet_id") or "").strip()
            timestamp = self._timestamp_seconds(row.get("timestamp"))
            if timestamp <= 0 and tweet_id:
                timestamp = float(_tweet_timestamp_from_id(tweet_id) or 0)
                if timestamp > 0:
                    row = dict(row)
                    row["timestamp"] = int(timestamp)
            if timestamp <= 0:
                continue
            age_seconds = now_ts - timestamp
            if age_seconds < 0 or age_seconds > max_age_seconds:
                continue
            if self.settings.x_require_same_local_day:
                created_local = datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone(zone)
                now_local = datetime.now(zone)
                if created_local.date() != now_local.date():
                    continue
            if tweet_id and tweet_id in seen_ids:
                continue
            if tweet_id:
                seen_ids.add(tweet_id)
            filtered.append(dict(row))
        filtered.sort(key=lambda item: self._timestamp_seconds(item.get("timestamp")), reverse=True)
        return filtered

    @staticmethod
    def _best_api_video_url(video: Dict[str, object]) -> str:
        variants = video.get("variants") or []
        mp4_variants = [
            item for item in variants
            if isinstance(item, dict) and str(item.get("content_type") or "").lower() == "video/mp4"
        ]
        if not mp4_variants:
            return ""
        best = max(mp4_variants, key=lambda item: int(item.get("bit_rate") or 0))
        return str(best.get("url") or "")

    @staticmethod
    def _normalize_handle(value: str) -> str:
        raw = (value or "").strip()
        if not raw:
            return ""
        if raw.startswith(("http://", "https://")):
            parsed = urlparse(raw)
            raw = (parsed.path or "").strip("/")
        raw = raw.replace("x.com/", "").replace("twitter.com/", "").strip("/")
        if "/" in raw:
            raw = raw.split("/", 1)[0]
        return raw.lstrip("@").strip()

    @staticmethod
    def _strip_urls(text: str) -> str:
        return re.sub(r"https?://\S+", "", text).strip()

    @staticmethod
    def _build_title(text: str) -> str:
        clean = re.sub(r"\s+", " ", text).strip()
        if len(clean) <= 88:
            return clean
        short = clean[:85].rsplit(" ", 1)[0].strip()
        return short or clean[:85].strip()

    @staticmethod
    def _age_hours(value: object) -> float:
        timestamp = XExtractionService._timestamp_seconds(value)
        if timestamp <= 0:
            return 0.0
        now = datetime.now(timezone.utc).timestamp()
        return max(0.0, (now - timestamp) / 3600.0)

    @staticmethod
    def _created_at_iso(timestamp: float) -> str:
        if timestamp <= 0:
            return ""
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(microsecond=0).isoformat()

    @staticmethod
    def _timestamp_seconds(value: object) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            pass
        raw = str(value or "").strip()
        if not raw:
            return 0.0
        normalized = raw.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).timestamp()
        except ValueError:
            return 0.0
