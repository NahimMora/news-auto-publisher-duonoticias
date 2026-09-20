from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

from .models import DiscoveredItem, content_hash


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def _create_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS items (
                key TEXT PRIMARY KEY,
                kind TEXT NOT NULL CHECK(kind IN ('news','video_link')),
                first_seen_at TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('seen','pending','processed','sent','failed')),
                attempts INTEGER NOT NULL DEFAULT 0,
                raw_json TEXT NOT NULL,
                processed_json TEXT,
                sent_at TEXT,
                last_error TEXT,
                retry_after TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_items_status_retry ON items(status, retry_after);
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.conn:
            yield self.conn

    def is_initialized(self) -> bool:
        row = self.conn.execute("SELECT value FROM metadata WHERE key='initial_sync_done'").fetchone()
        return row is not None

    def ingest(
        self,
        items: Sequence[DiscoveredItem],
        *,
        initial_mode: str = "mark_seen",
        last_n: int = 10,
    ) -> dict[str, int]:
        initial = not self.is_initialized()
        pending_keys: set[str] = set()
        if initial:
            if initial_mode == "process_all":
                pending_keys = {item.key for item in items}
            elif initial_mode == "last_n" and last_n:
                pending_keys = {item.key for item in items[-last_n:]}

        counts = {"new": 0, "changed_sent": 0, "unchanged": 0}
        now = utc_now()
        with self.transaction() as conn:
            for item in items:
                digest = content_hash(item.raw)
                row = conn.execute(
                    "SELECT content_hash, status FROM items WHERE key=?", (item.key,)
                ).fetchone()
                if row is None:
                    status = "pending" if (not initial or item.key in pending_keys) else "seen"
                    conn.execute(
                        """INSERT INTO items
                           (key,kind,first_seen_at,content_hash,status,raw_json)
                           VALUES (?,?,?,?,?,?)""",
                        (
                            item.key,
                            item.kind,
                            now,
                            digest,
                            status,
                            json.dumps(item.raw, ensure_ascii=False, sort_keys=True),
                        ),
                    )
                    counts["new"] += 1
                elif row["content_hash"] == digest:
                    counts["unchanged"] += 1
                elif row["status"] == "sent":
                    counts["changed_sent"] += 1
                    # Preserve both the sent payload and hash: v1 never resends mutations.
                else:
                    new_status = "pending" if row["status"] == "processed" else row["status"]
                    conn.execute(
                        """UPDATE items SET content_hash=?, raw_json=?, status=?,
                           processed_json=CASE WHEN status='processed' THEN NULL ELSE processed_json END,
                           retry_after=CASE WHEN status='processed' THEN NULL ELSE retry_after END
                           WHERE key=?""",
                        (
                            digest,
                            json.dumps(item.raw, ensure_ascii=False, sort_keys=True),
                            new_status,
                            item.key,
                        ),
                    )
            if initial:
                conn.execute(
                    "INSERT INTO metadata(key,value) VALUES('initial_sync_done',?)",
                    (now,),
                )
        return counts

    def list_for_processing(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM items WHERE status='pending' ORDER BY first_seen_at,key"))

    def list_for_sending(self, now: str | None = None) -> list[sqlite3.Row]:
        now = now or utc_now()
        return list(
            self.conn.execute(
                """SELECT * FROM items WHERE status='processed'
                   AND (retry_after IS NULL OR retry_after<=?) ORDER BY first_seen_at,key""",
                (now,),
            )
        )

    def mark_processed(self, key: str, processed: dict[str, Any]) -> bool:
        with self.transaction() as conn:
            cursor = conn.execute(
                """UPDATE items SET status='processed', processed_json=?, last_error=NULL
                   WHERE key=? AND status='pending'""",
                (json.dumps(processed, ensure_ascii=False, sort_keys=True), key),
            )
        return cursor.rowcount == 1

    def mark_sent(self, key: str) -> bool:
        with self.transaction() as conn:
            cursor = conn.execute(
                """UPDATE items SET status='sent', sent_at=?, last_error=NULL, retry_after=NULL
                   WHERE key=? AND status='processed'""",
                (utc_now(), key),
            )
        return cursor.rowcount == 1

    def mark_failed(self, key: str, error: str) -> bool:
        with self.transaction() as conn:
            cursor = conn.execute(
                """UPDATE items SET status='failed', attempts=attempts+1, last_error=?, retry_after=NULL
                   WHERE key=? AND status IN ('pending','processed')""",
                (error[:2000], key),
            )
        return cursor.rowcount == 1

    def mark_retry(self, key: str, error: str, retry_after: str, max_attempts: int) -> str:
        with self.transaction() as conn:
            row = conn.execute("SELECT attempts FROM items WHERE key=? AND status='processed'", (key,)).fetchone()
            if row is None:
                return "ignored"
            attempts = row["attempts"] + 1
            status = "failed" if attempts >= max_attempts else "processed"
            conn.execute(
                """UPDATE items SET status=?, attempts=?, last_error=?, retry_after=? WHERE key=?""",
                (status, attempts, error[:2000], None if status == "failed" else retry_after, key),
            )
        return status

    def counts(self) -> dict[str, int]:
        result = {name: 0 for name in ("seen", "pending", "processed", "sent", "failed")}
        for row in self.conn.execute("SELECT status, COUNT(*) AS count FROM items GROUP BY status"):
            result[row["status"]] = row["count"]
        return result

    @staticmethod
    def read_counts(path: str | Path) -> dict[str, int]:
        """Read counts without creating or mutating the database."""
        result = {name: 0 for name in ("seen", "pending", "processed", "sent", "failed")}
        db_path = Path(path)
        if not db_path.exists():
            return result
        uri = db_path.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        try:
            table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='items'"
            ).fetchone()
            if table:
                for row in conn.execute("SELECT status, COUNT(*) AS count FROM items GROUP BY status"):
                    if row["status"] in result:
                        result[row["status"]] = row["count"]
        finally:
            conn.close()
        return result

    def get(self, key: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM items WHERE key=?", (key,)).fetchone()

    def close(self) -> None:
        self.conn.close()
