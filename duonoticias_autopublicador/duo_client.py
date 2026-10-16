"""Bridge delivery: builds the v1 ingest payload from a bridge outbox row.

The HTTP transport is shared with the pipeline (publishers.duo_web).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx

from publishers.duo_web import IngestContractDelivery, SendResult, idempotency_key

__all__ = ["DuoClient", "SendResult", "build_payload", "idempotency_key"]


def build_payload(row: Any) -> dict[str, Any]:
    raw = json.loads(row["raw_json"])
    processed = json.loads(row["processed_json"])
    is_news = row["kind"] == "news"
    source_url = raw.get("url") if is_news else raw.get("source_url")
    published_url = (raw.get("web_url") or raw.get("url_wordpress")) if is_news else None
    title = raw.get("titulo") if is_news else raw.get("title")
    return {
        "schemaVersion": 1,
        "idempotencyKey": idempotency_key(row["key"]),
        "kind": row["kind"],
        "source": {"name": "HolaSalta", "url": source_url, "publishedUrl": published_url},
        "title": str(title or ""),
        "raw": raw,
        "processed": processed,
        "ingestedAt": datetime.now(timezone.utc).isoformat(),
    }


class DuoClient:
    def __init__(self, base_url: str, token: str, *, client: httpx.Client | None = None) -> None:
        self.delivery = IngestContractDelivery(base_url, token, client=client)

    def send(self, row: Any) -> SendResult:
        return self.delivery.send(build_payload(row))

    def close(self) -> None:
        self.delivery.close()
