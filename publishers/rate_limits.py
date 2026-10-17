"""Limites de tasa de Meta compartidos entre ciclos.

Un rechazo por limite (cupo de 24 h de Instagram, codigos 4/9/17/32/613,
subcodigo 2207042, HTTP 429) no es una falla del contenido: la plataforma queda
bloqueada hasta `until` y la pieza vuelve a la cola sin consumir reintentos.
El estado vive en data/runtime/meta_rate_limits.json (escritura atomica).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

_PATTERNS = [
    re.compile(r"""['"]code['"]:\s*(4|9|17|32|613)\b"""),
    re.compile(r"\(#(4|9|17|32|613)\)"),
    re.compile(r"2207042"),
    re.compile(r"limit reached", re.I),
    re.compile(r"rate limit", re.I),
    re.compile(r"request limit", re.I),
    re.compile(r"too many (calls|requests)", re.I),
    re.compile(r"status 429"),
]

# Cupo diario de Instagram: esperar mas; el resto suele ser transitorio.
_DAILY_CAP = re.compile(r"2207042|publishing limit reached", re.I)


def is_rate_limit_error(message: object) -> bool:
    text = str(message or "")
    return bool(text) and any(p.search(text) for p in _PATTERNS)


class RateLimitRegistry:
    def __init__(self, path: Path, *, short_minutes: int | None = None, daily_minutes: int | None = None) -> None:
        self.path = path
        self.short_minutes = short_minutes or int(os.getenv("DUO_RATE_LIMIT_BACKOFF_MINUTES", "30"))
        self.daily_minutes = daily_minutes or int(os.getenv("DUO_RATE_LIMIT_DAILY_BACKOFF_MINUTES", "180"))

    def _load(self) -> Dict[str, Dict[str, str]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data: Dict[str, Dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def block(self, platform: str, message: str, *, now: Optional[datetime] = None) -> datetime:
        now = now or datetime.now(timezone.utc)
        minutes = self.daily_minutes if _DAILY_CAP.search(message or "") else self.short_minutes
        until = now + timedelta(minutes=minutes)
        data = self._load()
        data[platform] = {"until": until.replace(microsecond=0).isoformat(), "reason": str(message or "")[:200]}
        self._save(data)
        return until

    def blocked_until(self, platform: str, *, now: Optional[datetime] = None) -> Optional[datetime]:
        now = now or datetime.now(timezone.utc)
        entry = self._load().get(platform) or {}
        try:
            until = datetime.fromisoformat(str(entry.get("until") or ""))
        except ValueError:
            return None
        return until if until > now else None

    def snapshot(self) -> Dict[str, Dict[str, str]]:
        now = datetime.now(timezone.utc)
        return {p: e for p, e in self._load().items() if self.blocked_until(p, now=now)}
