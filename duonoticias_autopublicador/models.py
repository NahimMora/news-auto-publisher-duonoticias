from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

Kind = Literal["news", "video_link"]


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").lower()
    port = parts.port
    netloc = hostname
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{hostname}:{port}"
    path = parts.path.rstrip("/") or "/"
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((scheme, netloc, path, query, ""))


def news_key(item: dict[str, Any]) -> str:
    if item.get("url"):
        return "source:" + str(item["url"])
    published = item.get("web_url") or item.get("url_wordpress")
    if published:
        return "web:" + str(published)
    return "title:" + str(item.get("titulo") or "").strip().lower()


def video_key(item: dict[str, Any]) -> str:
    return normalize_url(str(item["source_url"]))


def content_hash(item: dict[str, Any]) -> str:
    canonical = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def trace_id(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class DiscoveredItem:
    key: str
    kind: Kind
    raw: dict[str, Any]

