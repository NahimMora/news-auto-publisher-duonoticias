"""Delivery of pipeline content to the DuoNoticias web (Node CMS).

Two interchangeable transports, selected with ``DUO_WEB_MODE``:

- ``ingest``: ``POST /api/ingest/articles`` with Bearer token and
  ``Idempotency-Key`` (docs/INGEST_CONTRACT.md). Proposed contract; the web
  has to implement it.
- ``admin``: ``POST /api/admin/articles`` with ``x-admin-key`` (DUO_API.md).
  Exists today. It has no idempotency header, so a deterministic ``slug`` is
  sent and a 409 (slug already taken) counts as "already delivered".

``disabled`` (default) builds no publisher at all.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional, Protocol

import httpx

from storage.models import FormattedPackage, PublicationRecord

if TYPE_CHECKING:  # keeps the bridge importable without the pipeline settings stack
    from storage.settings import PipelineSettings

DUO_WEB_PLATFORM = "duo_web"

# Pipeline categories (config/sources.yaml) -> CMS enum (DUO_API.md section 4).
CATEGORY_MAP = {
    "espectaculos": "entertainment",
    "paparazzi": "entertainment",
    "viral": "entertainment",
    "economia": "business",
    "deportes": "sports",
    "tecnologia": "technology",
    "salud": "health",
    "internacional": "world",
    "politica": "politics",
}
CMS_CATEGORIES = {"politics", "sports", "technology", "entertainment", "world", "business", "health"}


@dataclass(frozen=True)
class SendResult:
    success: bool
    retryable: bool
    status_code: int | None
    error: str | None = None
    body: Dict[str, Any] = field(default_factory=dict)


def idempotency_key(item_key: str) -> str:
    return hashlib.sha256(item_key.encode("utf-8")).hexdigest()


class DuoWebDelivery(Protocol):
    mode: str

    def send(self, payload: Dict[str, Any]) -> SendResult: ...

    def close(self) -> None: ...


class _HttpDelivery:
    path = ""
    mode = ""

    def __init__(self, base_url: str, token: str, *, client: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.client = client or httpx.Client(timeout=30.0)

    def _headers(self, payload: Dict[str, Any]) -> Dict[str, str]:
        raise NotImplementedError

    def send(self, payload: Dict[str, Any]) -> SendResult:
        try:
            response = self.client.post(f"{self.base_url}{self.path}", json=payload, headers=self._headers(payload))
        except httpx.TransportError as exc:
            return SendResult(False, True, None, f"{type(exc).__name__}: {exc}")
        if response.status_code in {200, 201, 409}:
            return SendResult(True, False, response.status_code, body=_json_body(response))
        error = f"HTTP {response.status_code}: {response.text[:500]}"
        return SendResult(False, response.status_code >= 500, response.status_code, error)

    def close(self) -> None:
        self.client.close()


class IngestContractDelivery(_HttpDelivery):
    path = "/api/ingest/articles"
    mode = "ingest"

    def _headers(self, payload: Dict[str, Any]) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Idempotency-Key": str(payload["idempotencyKey"])}


class AdminArticlesDelivery(_HttpDelivery):
    path = "/api/admin/articles"
    mode = "admin"

    def _headers(self, payload: Dict[str, Any]) -> Dict[str, str]:
        return {"x-admin-key": self.token}


class DuoWebPublisher:
    def __init__(self, delivery: DuoWebDelivery, settings: PipelineSettings) -> None:
        self.delivery = delivery
        self.settings = settings

    @property
    def mode(self) -> str:
        return self.delivery.mode

    def build_payload(self, package: FormattedPackage, row: Dict[str, Any]) -> Dict[str, Any]:
        if self.mode == "admin":
            return build_admin_payload(package, row, default_category=self.settings.duo_web_default_category)
        return build_ingest_payload(package, row)

    def publish(self, package: FormattedPackage, *, row: Dict[str, Any], scheduled_for: str) -> PublicationRecord:
        payload = self.build_payload(package, row)
        result = self.delivery.send(payload)
        data = result.body.get("data") if isinstance(result.body.get("data"), dict) else {}
        return PublicationRecord(
            platform=DUO_WEB_PLATFORM,
            status="published" if result.success else "publish_failed",
            platform_post_id=str(data.get("id") or ""),
            caption=package.caption,
            post_type=package.post_type,
            scheduled_for=scheduled_for,
            published_at=_utc_now() if result.success else "",
            error_message="" if result.success else (result.error or "fallo de envio"),
            mode="live",
            dry_run=False,
            payload={"status_code": result.status_code, "retryable": result.retryable, "mode": self.mode},
        )

    def close(self) -> None:
        self.delivery.close()


def build_duo_web_publisher(settings: PipelineSettings, *, client: httpx.Client | None = None) -> Optional[DuoWebPublisher]:
    if settings.duo_web_mode == "disabled" or not settings.duo_web_url or not settings.duo_web_token:
        return None
    delivery_cls = AdminArticlesDelivery if settings.duo_web_mode == "admin" else IngestContractDelivery
    return DuoWebPublisher(delivery_cls(settings.duo_web_url, settings.duo_web_token, client=client), settings)


def build_ingest_payload(package: FormattedPackage, row: Dict[str, Any]) -> Dict[str, Any]:
    content_key = str(row.get("content_key") or package.content_key)
    return {
        "schemaVersion": 1,
        "idempotencyKey": idempotency_key("content:" + content_key),
        "kind": "video_link" if str(row.get("source_type") or "") == "x_video" else "news",
        "source": {"name": str(row.get("source") or ""), "url": str(row.get("canonical_url") or ""), "publishedUrl": None},
        "title": _title(package, row),
        "raw": _load_json(row.get("raw_payload_json")),
        "processed": {
            "caption": package.caption,
            "postType": package.post_type,
            "editorial": _load_json(row.get("editorial_json")),
        },
        "ingestedAt": _utc_now(),
    }


def build_admin_payload(package: FormattedPackage, row: Dict[str, Any], *, default_category: str = "world") -> Dict[str, Any]:
    title = _title(package, row)
    content_key = str(row.get("content_key") or package.content_key)
    summary = str(row.get("summary") or "").strip()
    body = str(row.get("body_text") or "").strip() or package.caption
    source_url = str(row.get("canonical_url") or "").strip()
    if source_url:
        body = f"{body}\n\nFuente: {source_url}"
    return {
        "title": title,
        # Deterministic slug: resending the same item collides instead of duplicating.
        "slug": f"{slugify(title)[:80]}-{content_key[:8]}".strip("-"),
        "description": (summary or package.caption)[:300],
        "content": body,
        "category": _category(row, default_category),
        "isActive": True,
        "isBreaking": False,
        "isHero": False,
        "isFeatured": False,
    }


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def _title(package: FormattedPackage, row: Dict[str, Any]) -> str:
    title = str(row.get("title") or "").strip()
    if title:
        return title
    return str(row.get("final_overlay") or package.caption.split("\n", 1)[0] or "").strip()


def _category(row: Dict[str, Any], default_category: str) -> str:
    tags = _load_json_any(row.get("tags_json"))
    for tag in tags if isinstance(tags, list) else []:
        mapped = CATEGORY_MAP.get(str(tag).strip().lower())
        if mapped:
            return mapped
    return default_category if default_category in CMS_CATEGORIES else "world"


def _json_body(response: httpx.Response) -> Dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _load_json(raw: object) -> Dict[str, Any]:
    value = _load_json_any(raw)
    return value if isinstance(value, dict) else {}


def _load_json_any(raw: object) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw or ""))
    except ValueError:
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
