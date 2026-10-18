"""Videos de X que llegan por el intercambio autorizado de HolaSalta.

Solo importa URLs puntuales de tuits (``C:\\sources\\x_video_sources.json``): no
recorre cuentas, timelines ni ``x.com/home``. El scraping autonomo de cuentas de
X (Playwright, API por handle, yt-dlp por perfil) se retiro en 2026-10: generaba
errores 429 y no es una fuente autorizada.

La importacion lee solo los metadatos del tuit (yt-dlp ``--dump-json``): texto,
autor, fecha y duracion. El video se descarga despues, recien si la pieza gana
un cupo (``utils/media_resolver.py``, con cache).
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from storage.models import Asset, ExtractedContent
from storage.settings import PipelineSettings, get_settings

LOGGER = logging.getLogger("duo.extractors.x")
_STATUS_RE = re.compile(r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/(\w+)/status/(\d+)")


class XImportError(RuntimeError):
    pass


def tweet_id_from_url(url: str) -> str:
    match = _STATUS_RE.search(url or "")
    return match.group(2) if match else ""


def fetch_tweet_info(url: str, timeout: int = 60) -> Dict[str, Any]:
    command = [sys.executable, "-m", "yt_dlp", "--dump-json", "--no-warnings", "--no-playlist", "--socket-timeout", "15", url]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise XImportError("timeout leyendo el tuit") from exc
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        reason = "sin_video" if "No video could be found" in stderr else "tuit_no_disponible"
        raise XImportError(f"{reason}: {stderr.splitlines()[-1][:200] if stderr else ''}")
    try:
        return json.loads((result.stdout or "").strip().splitlines()[0])
    except (ValueError, IndexError) as exc:
        raise XImportError("respuesta de yt-dlp ilegible") from exc


class XExtractionService:
    def __init__(self, settings: PipelineSettings | None = None, *, fetch=fetch_tweet_info) -> None:
        self.settings = settings or get_settings()
        self.fetch = fetch

    def import_url(self, url: str, *, dry_run: bool = False) -> ExtractedContent:
        match = _STATUS_RE.search(url or "")
        if not match:
            raise XImportError(f"no es un link de tuit: {url}")
        handle, tweet_id = match.group(1), match.group(2)
        tweet_url = f"https://x.com/{handle}/status/{tweet_id}"
        info = self.fetch(tweet_url)
        duration = float(info.get("duration") or 0.0)
        if duration <= 0:
            raise XImportError("sin_video: el tuit no tiene video")
        text = re.sub(r"https?://\S+", "", str(info.get("description") or info.get("title") or "")).strip()
        timestamp = int(info.get("timestamp") or 0)
        created = datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(microsecond=0).isoformat() if timestamp else ""
        return ExtractedContent(
            source="x",
            source_type="x_video",
            source_item_id=tweet_id,
            canonical_url=tweet_url,
            author=str(info.get("uploader") or ""),
            source_handle=str(info.get("uploader_id") or handle),
            title=_title(text),
            summary=text[:280],
            body_text=text,
            media_type="video",
            created_at=created,
            visible_metrics={
                "views": info.get("view_count") or 0,
                "likes": info.get("like_count") or 0,
                "reposts": info.get("repost_count") or 0,
                "comments": info.get("comment_count") or 0,
            },
            tags=["x", "holasalta_exchange"],
            ranking_signals={"duration_seconds": duration, "origin": "holasalta_exchange"},
            raw_payload={"tweet_url": tweet_url, "uploader": info.get("uploader"), "duration": duration, "dry_run": dry_run},
            assets=[
                Asset(
                    kind="video",
                    remote_url=tweet_url,
                    duration_seconds=duration,
                    meta={"video_kind": "tweet", "location": "cover", "provider": "x", "poster": str(info.get("thumbnail") or "")},
                )
            ],
        )


def _title(text: str) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= 88:
        return clean
    return clean[:85].rsplit(" ", 1)[0].strip() or clean[:85]
