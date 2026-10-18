"""Deteccion de videos reales dentro de articulos periodisticos.

No se limita al cuerpo: busca en la multimedia de portada, en datos
estructurados (JSON-LD, Arc/Fusion), en etiquetas ``video``/``source`` con
``src``/``data-*``, en iframes de reproductores y en publicaciones de X
incrustadas. Devuelve candidatos (``VideoCandidate``); la descarga, el chequeo de
duracion y de reproducibilidad se hacen despues (``utils/media_resolver.py``),
solo para las notas que lo necesitan.

Tipos de candidato (``kind``):
- ``mp4``      archivo directo
- ``hls``      manifiesto .m3u8
- ``tweet``    publicacion de X incrustada en la nota (no es scraping de cuentas)
- ``onvideo``  reproductor api.onvideo.news (El Tribuno), resuelve a HLS
- ``jwplayer`` media id de JW Player (Paparazzi), resuelve con su API publica
- ``youtube``  reproductor incrustado de YouTube
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

_TWEET_RE = re.compile(r"https?://(?:www\.|mobile\.)?(?:twitter|x)\.com/(\w+)/status/(\d+)")
_JW_PLAYER_SCRIPT_RE = re.compile(r"cdn\.jwplayer\.com/players/([A-Za-z0-9]{8})-[A-Za-z0-9]+\.js")
_JW_MP4_RE = re.compile(r"https://cdn\.jwplayer\.com/videos/([A-Za-z0-9]{8})-[A-Za-z0-9]+\.mp4")
_YOUTUBE_RE = re.compile(r"(?:youtube(?:-nocookie)?\.com/(?:embed/|watch\?v=)|youtu\.be/)([\w-]{11})")
_ONVIDEO_RE = re.compile(r"https?://api\.onvideo\.news/embed/([0-9a-f-]{36})")
_ISO_DURATION_RE = re.compile(
    r"^P(?:(?P<y>\d+)Y)?(?:(?P<mo>\d+)M)?(?:(?P<d>\d+)D)?(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>[\d.]+)S)?)?$"
)
_VIDEO_EXTENSIONS = (".mp4", ".m4v", ".mov", ".webm")
_BLOCKED_HOSTS = ("googletagmanager.com", "google-analytics.com", "doubleclick.net", "googlesyndication.com")


@dataclass
class VideoCandidate:
    url: str
    kind: str
    location: str = "body"  # cover | body | structured
    duration_seconds: Optional[float] = None
    poster: str = ""
    provider: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def parse_iso_duration(value: object) -> Optional[float]:
    """``PT2M5S`` / ``PT00H02M5S`` / ``P0Y0M0DT0H0M47S`` -> segundos."""
    raw = str(value or "").strip().upper()
    if not raw:
        return None
    match = _ISO_DURATION_RE.match(raw)
    if not match:
        return None
    parts = {key: float(val) for key, val in match.groupdict().items() if val}
    seconds = parts.get("d", 0) * 86400 + parts.get("h", 0) * 3600 + parts.get("m", 0) * 60 + parts.get("s", 0)
    return seconds or None


def classify_video_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()
    host = (urlparse(raw).hostname or "").lower()
    if any(host == blocked or host.endswith("." + blocked) for blocked in _BLOCKED_HOSTS):
        return ""
    if _TWEET_RE.search(raw):
        return "tweet"
    if _ONVIDEO_RE.search(raw):
        return "onvideo"
    if _YOUTUBE_RE.search(raw):
        return "youtube"
    if ".m3u8" in lowered:
        return "hls"
    path = urlparse(raw).path.lower()
    if path.endswith(_VIDEO_EXTENSIONS):
        return "mp4"
    return ""


def tweet_urls(text: str) -> List[str]:
    seen: List[str] = []
    for match in _TWEET_RE.finditer(text or ""):
        url = f"https://x.com/{match.group(1)}/status/{match.group(2)}"
        if url not in seen:
            seen.append(url)
    return seen


def dedupe_candidates(candidates: Iterable[VideoCandidate]) -> List[VideoCandidate]:
    """Primero portada, despues datos estructurados y cuerpo; sin repetir el mismo video."""
    order = {"cover": 0, "structured": 1, "body": 2}
    unique: Dict[str, VideoCandidate] = {}
    for candidate in candidates:
        if not candidate.url or not candidate.kind:
            continue
        key = _candidate_key(candidate)
        current = unique.get(key)
        if current is None or order.get(candidate.location, 3) < order.get(current.location, 3):
            if current is not None and candidate.duration_seconds is None:
                candidate.duration_seconds = current.duration_seconds
            unique[key] = candidate
        elif current.duration_seconds is None and candidate.duration_seconds:
            current.duration_seconds = candidate.duration_seconds
    return sorted(unique.values(), key=lambda item: order.get(item.location, 3))


def _candidate_key(candidate: VideoCandidate) -> str:
    if candidate.kind == "tweet":
        match = _TWEET_RE.search(candidate.url)
        return f"tweet:{match.group(2)}" if match else candidate.url
    if candidate.kind == "jwplayer":
        return f"jw:{candidate.meta.get('media_id') or candidate.url}"
    jw = _JW_MP4_RE.search(candidate.url)
    if jw:
        return f"jw:{jw.group(1)}"
    return candidate.url.split("?", 1)[0]


# ---------------------------------------------------------------------------
# HTML generico
# ---------------------------------------------------------------------------


def _absolute(url: str, base_url: str) -> str:
    raw = (url or "").strip()
    if not raw or raw.startswith("data:"):
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw
    return urljoin(base_url, raw) if base_url else raw


def _lazy_attrs(tag: Tag) -> Dict[str, str]:
    """``data-tadevel-lazy-attrs="src=https%3A%2F%2F..."`` (Informate Salta) y similares."""
    attrs: Dict[str, str] = {}
    for name, value in tag.attrs.items():
        if not isinstance(value, str) or not name.startswith("data-") or "lazy-attrs" not in name:
            continue
        for part in value.split("&"):
            key, _, raw = part.partition("=")
            if key and raw:
                attrs[key.strip()] = unquote(raw.strip())
    return attrs


def _media_src(tag: Tag) -> str:
    for attr in ("src", "data-src", "data-video-src", "data-lazy-src", "data-url"):
        value = tag.get(attr)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return _lazy_attrs(tag).get("src", "")


def videos_in_container(container: Optional[Tag], base_url: str, *, location: str) -> List[VideoCandidate]:
    """``video``/``source`` (src y data-*), iframes de reproductores, JW Player y tuits."""
    if container is None:
        return []
    found: List[VideoCandidate] = []
    for video in container.find_all("video"):
        poster = _absolute(str(video.get("poster") or ""), base_url)
        sources = [_media_src(video)] + [_media_src(source) for source in video.find_all("source")]
        for src in sources:
            url = _absolute(src, base_url)
            kind = classify_video_url(url)
            if kind in {"mp4", "hls"}:
                found.append(VideoCandidate(url=url, kind=kind, location=location, poster=poster))
    for iframe in container.find_all("iframe"):
        url = _absolute(_media_src(iframe), base_url)
        kind = classify_video_url(url)
        if kind:
            found.append(VideoCandidate(url=url, kind=kind, location=location, provider=kind))
    markup = str(container)
    for media_id in dict.fromkeys(_JW_PLAYER_SCRIPT_RE.findall(markup)):
        found.append(
            VideoCandidate(
                url=f"https://cdn.jwplayer.com/v2/media/{media_id}",
                kind="jwplayer",
                location=location,
                provider="jwplayer",
                meta={"media_id": media_id},
            )
        )
    for blockquote in container.select("blockquote.twitter-tweet, blockquote[class*=twitter]"):
        for url in tweet_urls(str(blockquote)):
            found.append(VideoCandidate(url=url, kind="tweet", location=location, provider="x"))
    return found


def json_ld_blocks(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except ValueError:
            continue
        stack = payload if isinstance(payload, list) else [payload]
        while stack:
            item = stack.pop(0)
            if not isinstance(item, dict):
                continue
            blocks.append(item)
            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)
            video = item.get("video")
            if isinstance(video, dict):
                stack.append(video)
            elif isinstance(video, list):
                stack.extend(video)
    return blocks


def videos_from_json_ld(soup: BeautifulSoup, *, location: str = "structured") -> List[VideoCandidate]:
    found: List[VideoCandidate] = []
    for block in json_ld_blocks(soup):
        if str(block.get("@type") or "") != "VideoObject":
            continue
        duration = parse_iso_duration(block.get("duration"))
        poster = block.get("thumbnailUrl")
        poster = poster[0] if isinstance(poster, list) and poster else poster
        for key in ("contentUrl", "embedUrl"):
            url = str(block.get(key) or "").strip()
            kind = classify_video_url(url)
            if kind:
                found.append(
                    VideoCandidate(url=url, kind=kind, location=location, duration_seconds=duration, poster=str(poster or ""))
                )
                break
    return found


def videos_from_meta(soup: BeautifulSoup) -> List[VideoCandidate]:
    found: List[VideoCandidate] = []
    for prop in ("og:video", "og:video:secure_url", "og:video:url", "twitter:player:stream"):
        tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        url = str(tag.get("content") or "").strip() if tag else ""
        kind = classify_video_url(url)
        if kind:
            found.append(VideoCandidate(url=url, kind=kind, location="cover"))
    return found


# ---------------------------------------------------------------------------
# Arc XP / Fusion (TN, Infobae)
# ---------------------------------------------------------------------------

_FUSION_RE = re.compile(r"Fusion\.globalContent\s*=\s*(\{.*?\});\s*Fusion\.", re.S)


def fusion_global_content(html: str) -> Dict[str, Any]:
    match = _FUSION_RE.search(html or "")
    if not match:
        return {}
    try:
        payload = json.loads(match.group(1))
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _arc_embed_video(element: Dict[str, Any], *, location: str) -> Optional[VideoCandidate]:
    element_type = str(element.get("type") or "")
    subtype = str(element.get("subtype") or "")
    if element_type == "custom_embed":
        config = ((element.get("embed") or {}).get("config") or {}) if isinstance(element.get("embed"), dict) else {}
        if subtype == "genoa" or str(config.get("subtype") or "") == "genoa":
            # TN: reproductor Genoa (vodgc). duration en milisegundos.
            if config.get("is_live_content"):
                return None
            url = str(config.get("highQuality") or config.get("m3u8") or config.get("lowQuality") or "")
            kind = classify_video_url(url)
            if not kind:
                return None
            duration = config.get("duration")
            seconds = float(duration) / 1000.0 if isinstance(duration, (int, float)) and duration > 1000 else None
            return VideoCandidate(
                url=url,
                kind=kind,
                location=location,
                duration_seconds=seconds,
                poster=str(config.get("thumbnail") or ""),
                provider="genoa",
                meta={"title": str(config.get("title") or ""), "content_id": str((element.get("embed") or {}).get("id") or "")},
            )
        if subtype == "video":
            # Infobae: JW Player (contentUrl mp4 + duration ISO).
            url = str(config.get("contentUrl") or "")
            kind = classify_video_url(url)
            if not kind:
                return None
            return VideoCandidate(
                url=url,
                kind=kind,
                location=location,
                duration_seconds=parse_iso_duration(config.get("duration")),
                poster=str(config.get("thumbnailUrl") or ""),
                provider="jwplayer",
                meta={"media_id": str(config.get("mediaId") or ""), "title": str(config.get("name") or "")},
            )
        return None
    if element_type == "video":
        # Video nativo de Arc: streams con url/stream_type.
        streams = [s for s in element.get("streams") or [] if isinstance(s, dict) and s.get("url")]
        mp4 = sorted((s for s in streams if s.get("stream_type") == "mp4"), key=lambda s: int(s.get("height") or 0))
        pick = next((s for s in mp4 if int(s.get("height") or 0) >= 480), mp4[-1] if mp4 else None)
        if pick is None:
            pick = next((s for s in streams if s.get("stream_type") == "ts"), None)
        if pick is None:
            return None
        url = str(pick.get("url") or "")
        duration = element.get("duration")
        return VideoCandidate(
            url=url,
            kind=classify_video_url(url) or "mp4",
            location=location,
            duration_seconds=float(duration) / 1000.0 if isinstance(duration, (int, float)) and duration > 1000 else None,
            provider="arc",
        )
    if element_type == "oembed_response" and subtype == "twitter":
        raw = element.get("raw_oembed") or {}
        url = str((raw.get("url") if isinstance(raw, dict) else "") or "")
        urls = tweet_urls(url) or tweet_urls(json.dumps(raw, ensure_ascii=False))
        if urls:
            return VideoCandidate(url=urls[0], kind="tweet", location=location, provider="x")
    return None


def arc_videos(global_content: Dict[str, Any]) -> List[VideoCandidate]:
    found: List[VideoCandidate] = []
    promo = (global_content.get("promo_items") or {}).get("basic") if isinstance(global_content.get("promo_items"), dict) else None
    if isinstance(promo, dict):
        candidate = _arc_embed_video(promo, location="cover")
        if candidate:
            found.append(candidate)
    for element in global_content.get("content_elements") or []:
        if isinstance(element, dict):
            candidate = _arc_embed_video(element, location="body")
            if candidate:
                found.append(candidate)
    return found


def arc_text(global_content: Dict[str, Any]) -> Dict[str, Any]:
    """Titulo, bajada, parrafos, fecha e imagen principal desde el contenido Arc."""
    headlines = global_content.get("headlines") or {}
    subheadlines = global_content.get("subheadlines") or {}
    description = global_content.get("description") or {}
    paragraphs: List[str] = []
    for element in global_content.get("content_elements") or []:
        if isinstance(element, dict) and element.get("type") in {"text", "header"}:
            text = re.sub(r"<[^>]+>", " ", str(element.get("content") or ""))
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) >= 30:
                paragraphs.append(text)
    image = ""
    promo = (global_content.get("promo_items") or {}).get("basic") if isinstance(global_content.get("promo_items"), dict) else None
    if isinstance(promo, dict) and promo.get("type") == "image":
        image = str(promo.get("url") or "")
    taxonomy = global_content.get("taxonomy") or {}
    section = ((taxonomy.get("primary_section") or {}).get("name") if isinstance(taxonomy, dict) else "") or ""
    return {
        "title": str(headlines.get("basic") or "").strip(),
        "summary": str(subheadlines.get("basic") or description.get("basic") or "").strip(),
        "paragraphs": paragraphs,
        "published": str(global_content.get("first_publish_date") or global_content.get("display_date") or ""),
        "image": image,
        "section": str(section),
    }
