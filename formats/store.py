"""Tablas propias de los formatos (misma base SQLite, sin tocar la cola de noticias).

- format_runs: una fila por turno programado (``digest:2026-10-18``), idempotencia.
- format_publications: cada salida a una red (historia, post, edicion, comentario).
- account_snapshots: seguidores por dia (crecimiento para el reporte).
- comment_replies: comentarios evaluados y respuestas (modo sombra o publicadas).
- service_health: ultimo estado de cada fuente de servicio.
- scraper_health: resultado del ultimo escaneo de cada fuente de noticias (avisos de falla).
- ops_reports: reportes de operaciones enviados o pendientes.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS format_runs (
    slot TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS format_publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot TEXT NOT NULL,
    kind TEXT NOT NULL,
    platform TEXT NOT NULL,
    post_type TEXT NOT NULL,
    status TEXT NOT NULL,
    media_id TEXT NOT NULL DEFAULT '',
    permalink TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_format_publications_created ON format_publications(created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_format_publications_once ON format_publications(slot, platform, post_type) WHERE status = 'published';
CREATE TABLE IF NOT EXISTS account_snapshots (
    day TEXT NOT NULL,
    platform TEXT NOT NULL,
    followers INTEGER,
    media_count INTEGER,
    created_at TEXT NOT NULL,
    PRIMARY KEY (day, platform)
);
CREATE TABLE IF NOT EXISTS comment_replies (
    comment_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    media_id TEXT NOT NULL,
    content_key TEXT NOT NULL DEFAULT '',
    comment_text TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    reply TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL,
    reply_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS service_health (
    source TEXT PRIMARY KEY,
    ok INTEGER NOT NULL,
    detail TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    last_ok_at TEXT
);
CREATE TABLE IF NOT EXISTS scraper_health (
    source TEXT PRIMARY KEY,
    ok INTEGER NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    items INTEGER NOT NULL DEFAULT 0,
    fails_in_row INTEGER NOT NULL DEFAULT 0,
    checked_at TEXT NOT NULL,
    last_ok_at TEXT,
    last_items_at TEXT
);
CREATE TABLE IF NOT EXISTS ops_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    period_start TEXT NOT NULL,
    status TEXT NOT NULL,
    recipient TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL DEFAULT '',
    html_path TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT ''
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class FormatsStore:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        with self.connection() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- turnos -------------------------------------------------------------

    def run_status(self, slot: str) -> str:
        with self.connection() as conn:
            row = conn.execute("SELECT status FROM format_runs WHERE slot = ?", (slot,)).fetchone()
        return str(row["status"]) if row else ""

    def runs_today(self, kind: str, day: str) -> int:
        with self.connection() as conn:
            row = conn.execute("SELECT COUNT(*) n FROM format_runs WHERE kind = ? AND slot LIKE ? AND status = 'done'", (kind, f"{kind}:{day}%")).fetchone()
        return int(row["n"])

    def set_run(self, slot: str, kind: str, status: str, detail: Optional[Dict[str, Any]] = None) -> None:
        now = utc_now()
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO format_runs(slot, kind, status, detail_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(slot) DO UPDATE SET status = excluded.status, detail_json = excluded.detail_json, updated_at = excluded.updated_at""",
                (slot, kind, status, json.dumps(detail or {}, ensure_ascii=False, default=str), now, now),
            )

    def last_run(self, kind: str) -> Optional[Dict[str, Any]]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM format_runs WHERE kind = ? AND status = 'done' ORDER BY updated_at DESC LIMIT 1", (kind,)).fetchone()
        return dict(row) if row else None

    # -- publicaciones ----------------------------------------------------------

    def save_publication(self, slot: str, kind: str, platform: str, post_type: str, status: str, *, media_id: str = "", permalink: str = "", error: str = "", payload: Optional[Dict[str, Any]] = None) -> None:
        with self.connection() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO format_publications(slot, kind, platform, post_type, status, media_id, permalink, error, payload_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (slot, kind, platform, post_type, status, media_id, permalink, error[:500], json.dumps(payload or {}, ensure_ascii=False, default=str), utc_now()),
            )

    def published(self, slot: str, platform: str, post_type: str) -> bool:
        with self.connection() as conn:
            row = conn.execute("SELECT 1 FROM format_publications WHERE slot = ? AND platform = ? AND post_type = ? AND status = 'published'", (slot, platform, post_type)).fetchone()
        return row is not None

    def publications_since(self, since: str) -> List[Dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM format_publications WHERE created_at >= ? ORDER BY created_at", (since,)).fetchall()
        return [dict(r) for r in rows]

    def stories_since(self, since: str, platform: str = "instagram") -> int:
        with self.connection() as conn:
            row = conn.execute("SELECT COUNT(*) n FROM format_publications WHERE post_type = 'story' AND platform = ? AND status = 'published' AND created_at >= ?", (platform, since)).fetchone()
        return int(row["n"])

    # -- seguidores -----------------------------------------------------------------

    def save_snapshot(self, day: str, platform: str, followers: Optional[int], media_count: Optional[int]) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO account_snapshots(day, platform, followers, media_count, created_at) VALUES (?, ?, ?, ?, ?)",
                (day, platform, followers, media_count, utc_now()),
            )

    def snapshots(self, platform: str, since_day: str) -> List[Dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM account_snapshots WHERE platform = ? AND day >= ? ORDER BY day", (platform, since_day)).fetchall()
        return [dict(r) for r in rows]

    def has_snapshot(self, day: str, platform: str) -> bool:
        with self.connection() as conn:
            return conn.execute("SELECT 1 FROM account_snapshots WHERE day = ? AND platform = ?", (day, platform)).fetchone() is not None

    # -- comentarios -------------------------------------------------------------------

    def known_comments(self, ids: List[str]) -> set:
        if not ids:
            return set()
        with self.connection() as conn:
            rows = conn.execute(f"SELECT comment_id FROM comment_replies WHERE comment_id IN ({','.join('?' * len(ids))})", ids).fetchall()
        return {str(r["comment_id"]) for r in rows}

    def save_comment(self, comment_id: str, *, platform: str, media_id: str, content_key: str, text: str, decision: str, reason: str, reply: str, mode: str, reply_id: str = "") -> None:
        now = utc_now()
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO comment_replies(comment_id, platform, media_id, content_key, comment_text, decision, reason, reply, mode, reply_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(comment_id) DO UPDATE SET decision = excluded.decision, reply = excluded.reply, mode = excluded.mode, reply_id = excluded.reply_id, updated_at = excluded.updated_at""",
                (comment_id, platform, media_id, content_key, text[:1000], decision, reason[:300], reply[:600], mode, reply_id, now, now),
            )

    def first_comment_at(self) -> Optional[str]:
        with self.connection() as conn:
            row = conn.execute("SELECT MIN(created_at) t FROM comment_replies").fetchone()
        return row["t"] if row and row["t"] else None

    def replies_since(self, since: str, mode: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM comment_replies WHERE created_at >= ?"
        params: List[Any] = [since]
        if mode:
            query += " AND mode = ?"
            params.append(mode)
        with self.connection() as conn:
            rows = conn.execute(query + " ORDER BY created_at", params).fetchall()
        return [dict(r) for r in rows]

    # -- salud de fuentes --------------------------------------------------------------------

    def save_health(self, health: Dict[str, Dict[str, Any]]) -> None:
        now = utc_now()
        with self.connection() as conn:
            for source, status in health.items():
                conn.execute(
                    """INSERT INTO service_health(source, ok, detail, checked_at, last_ok_at) VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(source) DO UPDATE SET ok = excluded.ok, detail = excluded.detail, checked_at = excluded.checked_at,
                       last_ok_at = COALESCE(excluded.last_ok_at, service_health.last_ok_at)""",
                    (source, int(bool(status.get("ok"))), str(status.get("detail") or "")[:300], now, now if status.get("ok") else None),
                )

    def save_scraper_result(self, source: str, *, ok: bool, items: int = 0, detail: str = "") -> None:
        """Escaneo de una fuente de noticias: ``items`` son las notas nuevas que devolvio."""
        now = utc_now()
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO scraper_health(source, ok, detail, items, fails_in_row, checked_at, last_ok_at, last_items_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source) DO UPDATE SET ok = excluded.ok, detail = excluded.detail, items = excluded.items,
                   fails_in_row = CASE WHEN excluded.ok = 1 THEN 0 ELSE scraper_health.fails_in_row + 1 END,
                   checked_at = excluded.checked_at,
                   last_ok_at = COALESCE(excluded.last_ok_at, scraper_health.last_ok_at),
                   last_items_at = COALESCE(excluded.last_items_at, scraper_health.last_items_at)""",
                (source, int(ok), detail[:300], int(items), 0 if ok else 1, now, now if ok else None, now if ok and items else None),
            )

    def scraper_health(self) -> List[Dict[str, Any]]:
        with self.connection() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM scraper_health ORDER BY source").fetchall()]

    def health(self) -> List[Dict[str, Any]]:
        with self.connection() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM service_health ORDER BY source").fetchall()]

    # -- reportes -------------------------------------------------------------------------

    def save_report(self, *, period_start: str, status: str, recipient: str, subject: str, html_path: str, error: str = "") -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO ops_reports(created_at, period_start, status, recipient, subject, html_path, error) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (utc_now(), period_start, status, recipient, subject[:300], html_path, error[:500]),
            )

    def last_report(self, status: str = "sent") -> Optional[Dict[str, Any]]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM ops_reports WHERE status = ? ORDER BY created_at DESC LIMIT 1", (status,)).fetchone()
        return dict(row) if row else None
