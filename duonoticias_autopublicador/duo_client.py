from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx


@dataclass(frozen=True)
class SendResult:
    success: bool
    retryable: bool
    status_code: int | None
    error: str | None = None


def idempotency_key(item_key: str) -> str:
    return hashlib.sha256(item_key.encode("utf-8")).hexdigest()


def build_payload(row: Any) -> dict[str, Any]:
    import json

    raw = json.loads(row["raw_json"])
    processed = json.loads(row["processed_json"])
    is_news = row["kind"] == "news"
    source_url = raw.get("url") if is_news else raw.get("source_url")
    published_url = (raw.get("web_url") or raw.get("url_wordpress")) if is_news else None
    return {
        "schemaVersion": 1,
        "idempotencyKey": idempotency_key(row["key"]),
        "kind": row["kind"],
        "source": {"name": "HolaSalta", "url": source_url, "publishedUrl": published_url},
        "title": str(raw.get("titulo") if is_news else raw.get("title") or ""),
        "raw": raw,
        "processed": processed,
        "ingestedAt": datetime.now(timezone.utc).isoformat(),
    }


class DuoClient:
    def __init__(self, base_url: str, token: str, *, client: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.client = client or httpx.Client(timeout=30.0)

    def send(self, row: Any) -> SendResult:
        payload = build_payload(row)
        try:
            response = self.client.post(
                f"{self.base_url}/api/ingest/articles",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Idempotency-Key": payload["idempotencyKey"],
                },
            )
        except httpx.TransportError as exc:
            return SendResult(False, True, None, f"{type(exc).__name__}: {exc}")
        if response.status_code in {200, 201, 409}:
            return SendResult(True, False, response.status_code)
        error = f"HTTP {response.status_code}: {response.text[:500]}"
        return SendResult(False, response.status_code >= 500, response.status_code, error)

    def close(self) -> None:
        self.client.close()

