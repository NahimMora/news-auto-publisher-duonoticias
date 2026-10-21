"""Persistencia de la cola editorial, acontecimientos, costos de IA y web futura.

Estados de una nota (``content_items.pipeline_status``) en el flujo horario:

    extracted      candidata: valida, todavia sin evaluar relevancia
    queued         pendiente: supero filtros y relevancia, espera cupo (max 12 h)
    selected       elegida para el ciclo en curso (cycle_id)
    editorialized  caption canonico listo            \
    formatted      pieza audiovisual/estatica lista   } procesando
    scheduled      lista para publicar en este ciclo /
    publishing     al menos una plataforma salio
    published      todas las plataformas requeridas publicadas
    retry          error recuperable: vuelve a queued en el proximo ciclo
    duplicate      otra version del mismo hecho fue elegida (puede ser promovida)
    discarded      descartada (motivo en last_error)
    expired        vencio las 12 h en la cola sin cupo: nunca se publica

``skipped``/``filtered`` (flujo anterior) siguen contando como descartadas.
Cada transicion queda en ``queue_events`` con su motivo.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Sequence

from storage.models import safe_json, utc_now_iso

DISCARD_STATES = ("discarded", "skipped", "filtered", "duplicate", "expired")
PROCESSING_STATES = ("selected", "editorialized", "formatted", "scheduled", "publishing")

_CONTENT_COLUMNS = {
    "event_key": "TEXT",
    "event_role": "TEXT",
    "source_group": "TEXT",
    "eligibility_json": "TEXT",
    "relevance_json": "TEXT",
    "relevance_score": "REAL",
    "relevance_version": "TEXT",
    "queue_entered_at": "TEXT",
    "queue_expires_at": "TEXT",
    "cycle_id": "TEXT",
    "media_json": "TEXT",
    "editorial_cache_key": "TEXT",
}

_TABLES = {
    "news_events": """
        CREATE TABLE IF NOT EXISTS news_events (
            event_key TEXT PRIMARY KEY,
            category TEXT,
            title TEXT,
            first_content_key TEXT,
            primary_content_key TEXT,
            member_count INTEGER NOT NULL DEFAULT 0,
            sources_json TEXT,
            first_eligible_at TEXT,
            relevance_score REAL,
            relevance_json TEXT,
            published_content_key TEXT,
            published_at TEXT,
            published_text TEXT,
            update_count INTEGER NOT NULL DEFAULT 0,
            last_update_reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
    "queue_events": """
        CREATE TABLE IF NOT EXISTS queue_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_key TEXT NOT NULL,
            event_key TEXT,
            from_status TEXT,
            to_status TEXT NOT NULL,
            reason TEXT,
            cycle_id TEXT,
            created_at TEXT NOT NULL
        )
    """,
    "llm_usage": """
        CREATE TABLE IF NOT EXISTS llm_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purpose TEXT NOT NULL,
            model TEXT,
            items INTEGER NOT NULL DEFAULT 1,
            input_tokens INTEGER,
            output_tokens INTEGER,
            total_tokens INTEGER,
            latency_ms INTEGER,
            ok INTEGER NOT NULL DEFAULT 1,
            error TEXT,
            cache_hit INTEGER NOT NULL DEFAULT 0,
            estimated_cost_usd REAL,
            cycle_id TEXT,
            content_keys_json TEXT,
            created_at TEXT NOT NULL
        )
    """,
    "cycles": """
        CREATE TABLE IF NOT EXISTS cycles (
            cycle_id TEXT PRIMARY KEY,
            mode TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            summary_json TEXT
        )
    """,
    "web_articles": """
        CREATE TABLE IF NOT EXISTS web_articles (
            event_key TEXT PRIMARY KEY,
            content_key TEXT NOT NULL,
            slug TEXT NOT NULL,
            title TEXT,
            seo_title TEXT,
            seo_description TEXT,
            excerpt TEXT,
            body_json TEXT,
            category TEXT,
            tags_json TEXT,
            main_image TEXT,
            video_json TEXT,
            sources_json TEXT,
            social_caption TEXT,
            status TEXT NOT NULL DEFAULT 'prepared',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """,
}

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_content_canonical_url ON content_items(canonical_url)",
    "CREATE INDEX IF NOT EXISTS idx_content_event ON content_items(event_key)",
    "CREATE INDEX IF NOT EXISTS idx_content_queue ON content_items(pipeline_status, queue_expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_content_cycle ON content_items(cycle_id)",
    "CREATE INDEX IF NOT EXISTS idx_queue_events_key ON queue_events(content_key, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_llm_usage_created ON llm_usage(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_events_updated ON news_events(updated_at)",
)


class EditorialStoreMixin:
    """Metodos de cola/eventos para ``PipelineStore`` (usa ``connection``/``_rows``)."""

    def _migrate_editorial_schema(self) -> None:
        for name, definition in _CONTENT_COLUMNS.items():
            self._ensure_column("content_items", name, definition)
        for table, ddl in _TABLES.items():
            self._ensure_table(table, ddl)
        for ddl in _INDEXES:
            self._ensure_index(ddl)

    # -- deduplicacion economica ------------------------------------------

    def known_url(self, url: str) -> bool:
        clean = str(url or "").strip().rstrip("/")
        if not clean:
            return False
        with self.connection() as conn:
            row = conn.execute(
                # Solo cuentan las notas del flujo nuevo (eligibility_json) o ya publicadas: lo que dejo
                # a medias el flujo anterior a 2026-10 se vuelve a procesar desde cero si reaparece.
                """
                SELECT 1 FROM content_items
                WHERE (canonical_url IN (?, ?) OR source_url IN (?, ?))
                  AND (eligibility_json IS NOT NULL OR pipeline_status IN ('published', 'publishing'))
                LIMIT 1
                """,
                (clean, clean + "/", clean, clean + "/"),
            ).fetchone()
        return row is not None

    # -- transiciones -------------------------------------------------------

    def transition(self, content_key: str, to_status: str, reason: str = "", *, cycle_id: str | None = None, **fields: Any) -> None:
        """Cambia el estado, registra el motivo y deja la transicion en queue_events."""
        now = utc_now_iso()
        assignments = ["pipeline_status = ?", "last_error = ?", "errors = ?", "updated_at = ?"]
        values: List[Any] = [to_status, reason[:500], reason[:500], now]
        if cycle_id is not None:
            assignments.append("cycle_id = ?")
            values.append(cycle_id)
        for column, value in fields.items():
            assignments.append(f"{column} = ?")
            values.append(value)
        with self.connection() as conn:
            row = conn.execute("SELECT pipeline_status, event_key FROM content_items WHERE content_key = ?", (content_key,)).fetchone()
            if row is None:
                return
            conn.execute(f"UPDATE content_items SET {', '.join(assignments)} WHERE content_key = ?", (*values, content_key))
            conn.execute(
                "INSERT INTO queue_events (content_key, event_key, from_status, to_status, reason, cycle_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (content_key, row["event_key"], row["pipeline_status"], to_status, reason[:500], cycle_id, now),
            )

    def queue_history(self, content_key: str) -> List[Dict[str, Any]]:
        return self._rows("SELECT * FROM queue_events WHERE content_key = ? ORDER BY id ASC", (content_key,))

    # -- acontecimientos ------------------------------------------------------

    def recent_event_members(self, since_iso: str, limit: int = 1500) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT content_key, event_key, event_role, source, source_group, title, summary,
                   substr(body_text, 1, 600) AS lead, created_at, extracted_at, canonical_url,
                   pipeline_status
            FROM content_items
            WHERE event_key IS NOT NULL AND COALESCE(created_at, extracted_at) >= ?
            ORDER BY extracted_at DESC
            LIMIT ?
            """,
            (since_iso, limit),
        )

    def get_event(self, event_key: str) -> Optional[Dict[str, Any]]:
        rows = self._rows("SELECT * FROM news_events WHERE event_key = ?", (event_key,))
        return rows[0] if rows else None

    def create_event(self, event_key: str, *, content_key: str, title: str, category: str, source: str) -> None:
        now = utc_now_iso()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO news_events (event_key, category, title, first_content_key, primary_content_key,
                    member_count, sources_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (event_key, category, title, content_key, content_key, safe_json([source]), now, now),
            )

    def attach_to_event(self, content_key: str, event_key: str, role: str, source: str) -> None:
        now = utc_now_iso()
        with self.connection() as conn:
            conn.execute(
                "UPDATE content_items SET event_key = ?, event_role = ?, updated_at = ? WHERE content_key = ?",
                (event_key, role, now, content_key),
            )
            row = conn.execute("SELECT sources_json FROM news_events WHERE event_key = ?", (event_key,)).fetchone()
            sources = json.loads(row["sources_json"] or "[]") if row else []
            if source and source not in sources:
                sources.append(source)
            conn.execute(
                """
                UPDATE news_events
                SET member_count = (SELECT COUNT(*) FROM content_items WHERE event_key = ?),
                    sources_json = ?, updated_at = ?
                WHERE event_key = ?
                """,
                (event_key, safe_json(sources), now, event_key),
            )

    def update_event(self, event_key: str, **fields: Any) -> None:
        if not fields:
            return
        assignments = ", ".join(f"{column} = ?" for column in fields)
        with self.connection() as conn:
            conn.execute(
                f"UPDATE news_events SET {assignments}, updated_at = ? WHERE event_key = ?",
                (*fields.values(), utc_now_iso(), event_key),
            )

    def event_members(self, event_key: str) -> List[Dict[str, Any]]:
        return self._rows("SELECT * FROM content_items WHERE event_key = ? ORDER BY extracted_at ASC", (event_key,))

    # -- relevancia y cola ------------------------------------------------------

    def pending_relevance(self, limit: int = 300) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT * FROM content_items
            WHERE pipeline_status = 'extracted'
              AND eligibility_json IS NOT NULL
              AND relevance_score IS NULL
              AND COALESCE(event_role, 'primary') IN ('primary', 'update')
            ORDER BY extracted_at ASC
            LIMIT ?
            """,
            (limit,),
        )

    def save_relevance(self, content_key: str, payload: Dict[str, Any], score: float, version: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE content_items
                SET relevance_json = ?, relevance_score = ?, relevance_version = ?,
                    score_total = ?, score_reason = ?, updated_at = ?
                WHERE content_key = ?
                """,
                (safe_json(payload), score, version, score, str(payload.get("motivo") or "")[:300], utc_now_iso(), content_key),
            )

    def queue_rows_for_allocation(self, now_iso: str) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT * FROM content_items
            WHERE pipeline_status IN ('queued', 'retry')
              AND eligibility_json IS NOT NULL
              AND (queue_expires_at IS NULL OR queue_expires_at > ?)
            ORDER BY relevance_score DESC, queue_entered_at ASC
            """,
            (now_iso,),
        )

    def expirable_rows(self, now_iso: str) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT content_key, title, source, queue_entered_at, queue_expires_at, pipeline_status
            FROM content_items
            WHERE pipeline_status IN ('queued', 'retry', 'selected')
              AND queue_expires_at IS NOT NULL AND queue_expires_at <= ?
            """,
            (now_iso,),
        )

    def rows_in_cycle(self, cycle_id: str) -> List[Dict[str, Any]]:
        return self._rows("SELECT * FROM content_items WHERE cycle_id = ? ORDER BY updated_at ASC", (cycle_id,))

    def stranded_processing_rows(self, current_cycle: str) -> List[Dict[str, Any]]:
        """Notas que quedaron a mitad de produccion en un ciclo anterior (reinicio, caida)."""
        placeholders = ",".join("?" for _ in PROCESSING_STATES)
        return self._rows(
            f"""
            SELECT * FROM content_items
            WHERE pipeline_status IN ({placeholders})
              AND eligibility_json IS NOT NULL
              AND COALESCE(cycle_id, '') != ?
            """,
            (*PROCESSING_STATES, current_cycle),
        )

    def pieces_published_since(self, since_iso: str) -> int:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(DISTINCT content_key) FROM publications
                WHERE status = 'published' AND COALESCE(published_at, updated_at) >= ?
                """,
                (since_iso,),
            ).fetchone()
        return int(row[0] or 0) if row else 0

    def queue_counts(self) -> Dict[str, int]:
        rows = self._rows("SELECT pipeline_status AS status, COUNT(*) AS total FROM content_items GROUP BY pipeline_status", ())
        return {str(row["status"]): int(row["total"]) for row in rows}

    # -- costos de IA -------------------------------------------------------------

    def record_llm_usage(
        self,
        *,
        purpose: str,
        model: str,
        items: int,
        input_tokens: Optional[int],
        output_tokens: Optional[int],
        latency_ms: int,
        ok: bool,
        error: str = "",
        cache_hit: bool = False,
        estimated_cost_usd: Optional[float] = None,
        cycle_id: str | None = None,
        content_keys: Sequence[str] = (),
    ) -> None:
        total = (input_tokens or 0) + (output_tokens or 0) if (input_tokens is not None or output_tokens is not None) else None
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO llm_usage (purpose, model, items, input_tokens, output_tokens, total_tokens, latency_ms,
                    ok, error, cache_hit, estimated_cost_usd, cycle_id, content_keys_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    purpose, model, int(items), input_tokens, output_tokens, total, int(latency_ms), int(bool(ok)),
                    error[:300], int(bool(cache_hit)), estimated_cost_usd, cycle_id, safe_json(list(content_keys)[:50]), utc_now_iso(),
                ),
            )

    def llm_usage_summary(self, since_iso: str) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT purpose, model,
                   COUNT(*) AS calls,
                   SUM(CASE WHEN cache_hit = 1 THEN 1 ELSE 0 END) AS cache_hits,
                   SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END) AS errors,
                   SUM(items) AS items,
                   SUM(input_tokens) AS input_tokens,
                   SUM(output_tokens) AS output_tokens,
                   SUM(estimated_cost_usd) AS estimated_cost_usd,
                   ROUND(AVG(latency_ms)) AS avg_latency_ms
            FROM llm_usage
            WHERE created_at >= ?
            GROUP BY purpose, model
            ORDER BY calls DESC
            """,
            (since_iso,),
        )

    # -- ciclos ---------------------------------------------------------------------

    def start_cycle(self, cycle_id: str, mode: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO cycles (cycle_id, mode, started_at) VALUES (?, ?, ?)",
                (cycle_id, mode, utc_now_iso()),
            )

    def finish_cycle(self, cycle_id: str, summary: Dict[str, Any]) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE cycles SET finished_at = ?, summary_json = ? WHERE cycle_id = ?",
                (utc_now_iso(), safe_json(summary), cycle_id),
            )

    # -- web futura ----------------------------------------------------------------

    def upsert_web_article(self, payload: Dict[str, Any]) -> None:
        now = utc_now_iso()
        columns = (
            "event_key", "content_key", "slug", "title", "seo_title", "seo_description", "excerpt", "body_json",
            "category", "tags_json", "main_image", "video_json", "sources_json", "social_caption", "status",
        )
        values = [payload.get(column) for column in columns]
        with self.connection() as conn:
            conn.execute(
                f"""
                INSERT INTO web_articles ({', '.join(columns)}, created_at, updated_at)
                VALUES ({', '.join('?' for _ in columns)}, ?, ?)
                ON CONFLICT(event_key) DO UPDATE SET
                    {', '.join(f'{c}=excluded.{c}' for c in columns if c != 'event_key')},
                    updated_at=excluded.updated_at
                """,
                (*values, now, now),
            )

    def web_articles(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._rows("SELECT * FROM web_articles ORDER BY updated_at DESC LIMIT ?", (limit,))

    def slug_taken(self, slug: str, event_key: str) -> bool:
        with self.connection() as conn:
            row = conn.execute("SELECT 1 FROM web_articles WHERE slug = ? AND event_key != ? LIMIT 1", (slug, event_key)).fetchone()
        return row is not None
