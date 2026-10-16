from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

from extractors.x.network_parser import extract_video_tweets_from_payload
from extractor_x.extractor_x_videos import _tweet_timestamp_from_id
from storage.settings import PipelineSettings, get_settings


class PlaywrightAuthenticatedXStrategy:
    def __init__(self, settings: PipelineSettings | None = None) -> None:
        self.settings = settings or get_settings()

    def extract(self, handle: str, limit: int, max_age_hours: int) -> List[Dict[str, Any]]:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return []

        captured_payloads: List[Dict[str, Any]] = []
        browser = None
        context = None
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=self.settings.x_headless)
                if self.settings.x_session_storage_state.exists():
                    context = browser.new_context(storage_state=str(self.settings.x_session_storage_state))
                else:
                    context = browser.new_context()
                page = context.new_page()
                page.on("response", lambda response: self._capture_response(response, captured_payloads))
                page.goto(self._target_url(handle), wait_until="domcontentloaded", timeout=45000)
                if "/i/flow/login" in page.url or "/login" in page.url:
                    return []

                for _ in range(max(1, self.settings.x_max_scrolls)):
                    page.mouse.wheel(0, 2400)
                    page.wait_for_timeout(int(self.settings.x_scroll_pause_seconds * 1000))
                    parsed = self._collect_items(captured_payloads, max_age_hours=max_age_hours, limit=limit)
                    if len(parsed) >= limit:
                        break

                parsed = self._collect_items(captured_payloads, max_age_hours=max_age_hours, limit=limit)
                if self.settings.debug:
                    self._persist_debug_payloads(handle, captured_payloads)
                return parsed
        except Exception:
            return []
        finally:
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass
            try:
                if browser is not None:
                    browser.close()
            except Exception:
                pass

    def _capture_response(self, response: Any, captured_payloads: List[Dict[str, Any]]) -> None:
        url = response.url or ""
        if "graphql" not in url:
            return
        content_type = (response.headers or {}).get("content-type", "")
        if "json" not in content_type:
            return
        try:
            payload = response.json()
        except Exception:
            try:
                payload = json.loads(response.text())
            except Exception:
                return
        captured_payloads.append({"url": url, "payload": payload})

    def _collect_items(
        self,
        captured_payloads: List[Dict[str, Any]],
        *,
        max_age_hours: int,
        limit: int,
    ) -> List[Dict[str, Any]]:
        now_ts = time.time()
        max_age_seconds = max_age_hours * 3600
        rows: List[Dict[str, Any]] = []
        seen = set()
        for item in captured_payloads:
            payload = item.get("payload")
            if not isinstance(payload, dict):
                continue
            for parsed in extract_video_tweets_from_payload(payload):
                tweet_id = parsed.get("tweet_id")
                if not tweet_id or tweet_id in seen:
                    continue
                if not parsed.get("media"):
                    continue
                timestamp = int(parsed.get("timestamp") or 0) or int(_tweet_timestamp_from_id(str(tweet_id)) or 0)
                if timestamp <= 0:
                    continue
                if (now_ts - timestamp) > max_age_seconds:
                    continue
                parsed["timestamp"] = timestamp
                seen.add(tweet_id)
                rows.append(parsed)
        rows.sort(key=lambda row: int(row.get("timestamp") or 0), reverse=True)
        return rows[:limit]

    def _persist_debug_payloads(self, handle: str, captured_payloads: List[Dict[str, Any]]) -> None:
        if not captured_payloads:
            return
        self.settings.x_capture_debug_dir.mkdir(parents=True, exist_ok=True)
        path = self.settings.x_capture_debug_dir / f"{handle}_payloads.json"
        path.write_text(json.dumps(captured_payloads, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _target_url(handle: str) -> str:
        normalized = str(handle or "").strip().lower()
        if normalized == "home":
            return "https://x.com/home?lang=es"
        return f"https://x.com/{handle}/media"
