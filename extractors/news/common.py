from __future__ import annotations

import hashlib
import html
import re
from pathlib import Path
from typing import Dict, Iterable, List
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from storage.models import Asset, ExtractedContent


def strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def normalize_url(url: str, base_url: str = "") -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw
    if base_url:
        raw = urljoin(base_url, raw)
    parsed = urlparse(raw)
    clean = parsed._replace(fragment="", query="")
    return urlunparse(clean).rstrip("/")


def normalize_media_url(url: str, base_url: str = "") -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw
    if base_url:
        raw = urljoin(base_url, raw)
    parsed = urlparse(raw)
    clean = parsed._replace(fragment="")
    return urlunparse(clean).rstrip("/")


def stable_item_id(url: str, title: str = "") -> str:
    source = normalize_url(url) or title
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]


def extract_article_fields(html_text: str, url: str, title_hint: str = "") -> Dict[str, object]:
    soup = BeautifulSoup(html_text or "", "html.parser")
    title = _first_meta(soup, "og:title") or _tag_text(soup, "h1") or title_hint
    summary = (
        _first_meta(soup, "og:description")
        or _first_meta_name(soup, "description")
        or ""
    )
    image = _first_meta(soup, "og:image")
    published = _first_meta(soup, "article:published_time")
    paragraphs = []
    for element in soup.select("article p, main p, .article p, .note p, p"):
        text = strip_html(element.get_text(" ", strip=True))
        if len(text) < 35:
            continue
        if text in paragraphs:
            continue
        paragraphs.append(text)
        if len(paragraphs) >= 6:
            break
    videos = []
    for tag in soup.select("video source[src], video[src], iframe[src]"):
        src = tag.get("src") or ""
        normalized_src = normalize_url(src, url) if src else ""
        if normalized_src and _looks_like_video_url(normalized_src):
            videos.append(normalized_src)
    images = [normalize_media_url(image, url)] if image else []
    return {
        "title": strip_html(str(title)),
        "summary": strip_html(str(summary)),
        "body_text": "\n".join(paragraphs),
        "image_urls": [item for item in images if item],
        "video_urls": [item for item in videos if item],
        "published": str(published or ""),
    }


def content_from_raw(
    *,
    source: str,
    source_type: str,
    raw: Dict[str, object],
    category: str = "",
) -> ExtractedContent:
    image_candidates = _collect_values(
        raw,
        "imagen_optimizada",
        "imagen",
        "image",
        "image_url",
    )
    image_candidates.extend(str(item) for item in raw.get("imagenes_url", []) or [] if item)
    image_candidates.extend(str(item) for item in raw.get("image_urls", []) or [] if item)
    for item in raw.get("imagenes_secundarias", []) or []:
        if isinstance(item, dict):
            image_candidates.extend(_collect_values(item, "optimizada", "original", "url"))
        elif item:
            image_candidates.append(str(item))

    video_candidates = _collect_values(raw, "video", "video_path")
    video_candidates.extend(str(item) for item in raw.get("videos", []) or [] if item)
    video_candidates.extend(str(item) for item in raw.get("videos_url", []) or [] if item)
    video_candidates.extend(str(item) for item in raw.get("videos_locales", []) or [] if item)
    video_candidates.extend(str(item) for item in raw.get("video_urls", []) or [] if item)
    video_candidates = [candidate for candidate in video_candidates if _looks_like_video_url(candidate)]

    assets: List[Asset] = []
    seen = set()
    for candidate in image_candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        assets.append(Asset(kind="image", path="" if candidate.startswith("http") else candidate, remote_url=candidate if candidate.startswith("http") else ""))
    for candidate in video_candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        assets.append(Asset(kind="video", path="" if candidate.startswith("http") else candidate, remote_url=candidate if candidate.startswith("http") else ""))

    media_type = "video" if any(asset.kind == "video" for asset in assets) else "image"
    if media_type == "image" and len([asset for asset in assets if asset.kind == "image"]) > 1:
        media_type = "carousel"

    paragraphs = raw.get("parrafos") or []
    if isinstance(paragraphs, list):
        body_text = "\n".join(str(item) for item in paragraphs if item).strip()
    else:
        body_text = str(raw.get("body_text") or raw.get("text") or "").strip()
    if not body_text:
        body_text = str(raw.get("body_text") or "").strip()

    canonical_url = normalize_url(str(raw.get("url") or raw.get("source_url") or raw.get("canonical_url") or ""))
    title = strip_html(str(raw.get("titulo") or raw.get("title") or ""))
    summary = strip_html(str(raw.get("extracto") or raw.get("summary") or ""))
    tags = [source]
    if category:
        tags.append(category)
    raw_category = str(raw.get("categoria") or raw.get("category") or "").strip()
    if raw_category:
        tags.append(raw_category)
    return ExtractedContent(
        source=source,
        source_type=source_type,
        source_item_id=str(raw.get("id") or raw.get("slug") or stable_item_id(canonical_url, title)).strip(),
        canonical_url=canonical_url,
        author=str(raw.get("autor") or raw.get("author") or "").strip(),
        title=title,
        summary=summary,
        body_text=body_text,
        media_type=media_type,
        created_at=str(raw.get("fecha_publicacion") or raw.get("published") or raw.get("created_at") or "").strip(),
        tags=tags,
        ranking_signals={
            "paragraph_count": len([part for part in body_text.splitlines() if part.strip()]),
            "asset_count": len(assets),
            "has_video": any(asset.kind == "video" for asset in assets),
        },
        raw_payload=raw,
        assets=assets,
    )


def _collect_values(raw: Dict[str, object], *keys: str) -> List[str]:
    values = []
    for key in keys:
        value = str(raw.get(key) or "").strip()
        if value:
            values.append(value)
    return values


def _looks_like_video_url(value: str) -> bool:
    raw = (value or "").strip()
    if not raw:
        return False
    parsed = urlparse(raw)
    lowered = raw.lower()
    hostname = (parsed.hostname or "").lower()
    if not parsed.scheme and Path(raw).suffix.lower() in {".mp4", ".mov", ".m4v", ".webm", ".m3u8"}:
        return True
    if parsed.scheme not in {"http", "https"}:
        return False
    blocked_hosts = (
        "googletagmanager.com",
        "google-analytics.com",
        "doubleclick.net",
        "facebook.com",
        "connect.facebook.net",
    )
    if any(hostname == host or hostname.endswith(f".{host}") for host in blocked_hosts):
        return False
    path = parsed.path.lower()
    return path.endswith((".mp4", ".mov", ".m4v", ".webm", ".m3u8")) or ".m3u8" in lowered


def _first_meta(soup: BeautifulSoup, property_name: str) -> str:
    tag = soup.find("meta", property=property_name)
    return str(tag.get("content") or "").strip() if tag else ""


def _first_meta_name(soup: BeautifulSoup, name: str) -> str:
    tag = soup.find("meta", attrs={"name": name})
    return str(tag.get("content") or "").strip() if tag else ""


def _tag_text(soup: BeautifulSoup, selector: str) -> str:
    tag = soup.select_one(selector)
    return tag.get_text(" ", strip=True) if tag else ""
