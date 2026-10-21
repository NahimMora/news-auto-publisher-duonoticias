"""Links de videos de X que recolecta HolaSalta, via archivo de intercambio.

HolaSalta escribe ``C:\\sources\\x_video_sources.json`` (lista de la mas nueva a la
mas vieja, maximo 100 entradas) y lo reemplaza de forma atomica. Reglas:

- Solo lectura: se lee de una vez y se suelta; nunca se escribe, mueve ni borra
  (lo usan HolaSalta y LVR).
- Estado propio en ``data/runtime/x_video_feed_state.json``; nunca el de LVR.
- Archivo ausente, a medio escribir o con JSON invalido no es error: se reintenta
  en el proximo ciclo.
- Solo URLs https de x.com/twitter.com con ``/status/``.
- Dedupe por ``job_id`` y por ID del tweet (HolaSalta puede repetir el tweet con
  otro job_id).
- Se procesa del mas viejo al mas nuevo y se descartan los de mas de
  ``X_VIDEO_FEED_MAX_AGE_HOURS``.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

X_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}
_TWEET_ID = re.compile(r"/status/(\d+)")
# Intentos de importacion antes de dar un job por perdido.
MAX_ATTEMPTS = 3
# El estado guarda como mucho esta cantidad de jobs (la ventana del feed es de 100).
STATE_LIMIT = 1000


def tweet_key(url: str) -> str:
    match = _TWEET_ID.search(url)
    return f"x:{match.group(1)}" if match else url


def is_valid_x_url(url: str) -> bool:
    parts = urlparse(url)
    return parts.scheme == "https" and parts.netloc.lower() in X_HOSTS and "/status/" in parts.path


def _parse_created(raw: object) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(raw or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class XVideoFeed:
    def __init__(self, feed_path: Path, state_path: Path, *, max_age_hours: float = 24.0) -> None:
        self.feed_path = feed_path
        self.state_path = state_path
        self.max_age_hours = max_age_hours
        self.logger = logging.getLogger("duo.extractors.x_video_feed")

    def read_feed(self) -> List[Dict[str, Any]]:
        try:
            data = json.loads(self.feed_path.read_text(encoding="utf-8"))  # lee y suelta
        except (OSError, ValueError):
            return []  # se reintenta en el proximo ciclo
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    def pending_jobs(self, *, now: datetime | None = None) -> List[Tuple[str, str]]:
        """Registra los jobs nuevos y devuelve los pendientes, del mas viejo al mas nuevo."""
        now = now or datetime.now(timezone.utc)
        state = self._load_state()
        jobs: Dict[str, Dict[str, Any]] = state["jobs"]
        seen_tweets = {str(job.get("tweet_key") or "") for job in jobs.values()}
        max_age = self.max_age_hours * 3600
        for entry in reversed(self.read_feed()):  # mas viejo primero
            job_id = str(entry.get("job_id") or "")
            url = str(entry.get("url") or "").strip()
            if not job_id or job_id in jobs or not is_valid_x_url(url):
                continue
            key = tweet_key(url)
            created = _parse_created(entry.get("created_at"))
            if key in seen_tweets:
                status = "skipped_duplicate"
            elif created is None or (now - created).total_seconds() > max_age:
                status = "skipped_old"
            else:
                status = "pending"
            jobs[job_id] = {
                "url": url,
                "tweet_key": key,
                "created_at": created.isoformat() if created else "",
                "status": status,
                "attempts": 0,
            }
            seen_tweets.add(key)
        self._save_state(state)
        pending = [(job_id, job) for job_id, job in jobs.items() if job.get("status") == "pending"]
        pending.sort(key=lambda item: str(item[1].get("created_at") or ""))
        return [(job_id, str(job["url"])) for job_id, job in pending]

    def mark(self, job_id: str, status: str, *, content_key: str = "", error: str = "") -> None:
        """status: imported | skipped_duplicate | failed (reintenta hasta MAX_ATTEMPTS)."""
        state = self._load_state()
        job = state["jobs"].get(job_id)
        if job is None:
            return
        if status == "failed":
            job["attempts"] = int(job.get("attempts") or 0) + 1
            job["last_error"] = error[:300]
            if job["attempts"] < MAX_ATTEMPTS:
                status = "pending"
        job["status"] = status
        if content_key:
            job["content_key"] = content_key
        self._save_state(state)

    def _load_state(self) -> Dict[str, Any]:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        if not isinstance(state, dict) or not isinstance(state.get("jobs"), dict):
            state = {"jobs": {}}
        return state

    def _save_state(self, state: Dict[str, Any]) -> None:
        jobs = state["jobs"]
        if len(jobs) > STATE_LIMIT:
            # Los mas viejos ya salieron de la ventana del feed.
            ordered = sorted(jobs.items(), key=lambda item: str(item[1].get("created_at") or ""))
            state["jobs"] = dict(ordered[-STATE_LIMIT:])
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")  # escritura atomica
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.state_path)
