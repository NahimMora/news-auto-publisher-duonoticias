"""Scrape a single Paparazzi article using the WordPress API + Scrapy selectors."""
import html
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from parsel import Selector

try:
    from utils.http_client import HttpClient, download_to_file
except ImportError:  # pragma: no cover
    import sys
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT))
    from utils.http_client import HttpClient, download_to_file

from scrapping.paparazzi.scrapy_fetcher import fetch_html_map

try:
    from scrapping.paparazzi.config import (
        POSTS_ENDPOINT,
        REQUEST_TIMEOUT,
        get_random_user_agent,
        IMAGE_EXCLUDE_PATTERNS,
        TEXT_EXCLUDE_PATTERNS,
        BASE_URL,
        FOTOS_PATH,
        VIDEOS_PATH,
        VIDEO_DOWNLOAD_TIMEOUT,
    )
    from scrapping.paparazzi.logger import ScraperLogger
except ImportError:
    from .config import (
        POSTS_ENDPOINT,
        REQUEST_TIMEOUT,
        get_random_user_agent,
        IMAGE_EXCLUDE_PATTERNS,
        TEXT_EXCLUDE_PATTERNS,
        BASE_URL,
        FOTOS_PATH,
        VIDEOS_PATH,
        VIDEO_DOWNLOAD_TIMEOUT,
    )
    from .logger import ScraperLogger

try:
    from utils.image_processor import process_image, optimize_image
except ImportError:
    import sys
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT))
    from utils.image_processor import process_image, optimize_image


def _strip_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = re.sub(r"\s+", " ", text).strip()
    return html.unescape(text).strip()


def _sanitize_filename(text: str, max_length: int = 60) -> str:
    safe = re.sub(r"[^\w\s-]", "", text or "")
    safe = re.sub(r"[-\s]+", "_", safe).strip("_")
    if not safe:
        safe = "noticia"
    if len(safe) > max_length:
        safe = safe[:max_length]
    return safe


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return BASE_URL.rstrip("/") + url
    return url


def _extract_srcset_best(srcset: str) -> str:
    if not srcset:
        return ""
    parts = [p.strip() for p in srcset.split(",") if p.strip()]
    if not parts:
        return ""
    last = parts[-1].split(" ")[0]
    return last


def _is_excluded_image(url: str) -> bool:
    if not url:
        return True
    for pattern in IMAGE_EXCLUDE_PATTERNS:
        if pattern.lower() in url.lower():
            return True
    return False


def _is_excluded_text(text: str) -> bool:
    if not text or len(text) < 20:
        return True
    for pattern in TEXT_EXCLUDE_PATTERNS:
        if pattern.lower() in text.lower():
            return True
    return False


def _extract_images_from_html(html_content: str) -> List[str]:
    sel = Selector(text=html_content or "")
    urls: List[str] = []
    for img in sel.xpath("//img"):
        src = (
            img.attrib.get("data-src")
            or img.attrib.get("data-lazy-src")
            or img.attrib.get("data-original")
            or img.attrib.get("src")
        )
        if not src:
            srcset = img.attrib.get("srcset")
            if srcset:
                src = _extract_srcset_best(srcset)
        if not src:
            continue
        src = _normalize_url(src)
        if not _is_excluded_image(src):
            urls.append(src)
    return urls


def _extract_videos_from_html(html_content: str) -> List[str]:
    sel = Selector(text=html_content or "")
    urls = set()

    for src in sel.xpath("//iframe/@src | //iframe/@data-src").getall():
        if src:
            urls.add(_normalize_url(src))

    for src in sel.xpath("//video/@src | //video/source/@src").getall():
        if src:
            urls.add(_normalize_url(src))

    if html_content:
        for match in re.findall(r"https?://[^\s\"']+", html_content):
            if any(provider in match for provider in ["youtube.com", "youtu.be", "vimeo.com", "tiktok.com", "instagram.com", ".mp4"]):
                urls.add(match)

    return list(urls)


def _find_jwplayer_scripts(page_html: str) -> List[str]:
    if not page_html:
        return []
    sel = Selector(text=page_html)
    return sel.xpath("//script[contains(@src, 'cdn.jwplayer.com/players/')]/@src").getall()


def _extract_jwplayer_playback_url(player_js_url: str) -> Optional[str]:
    try:
        client = HttpClient(headers={"User-Agent": get_random_user_agent()}, timeout=REQUEST_TIMEOUT, retries=3)
        resp = client.get(player_js_url)
        resp.raise_for_status()
        text = resp.text
        match = re.search(r'"playlist"\s*:\s*"(//cdn\\.jwplayer\\.com[^\"]+playback\\.json[^\"]*)"', text)
        if match:
            return "https:" + match.group(1)
        match = re.search(r"(https?://cdn\\.jwplayer\\.com/[^\"']+playback\\.json[^\"']*)", text)
        if match:
            return match.group(1)
    except Exception:
        return None
    finally:
        try:
            client.close()
        except Exception:
            pass
    return None


def _extract_jwplayer_media_id(player_js_url: str) -> Optional[str]:
    if not player_js_url:
        return None
    match = re.search(r"/players/([a-zA-Z0-9]+)-", player_js_url)
    if match:
        return match.group(1)
    return None


def _fetch_jwplayer_v2_media(media_id: str) -> List[dict]:
    if not media_id:
        return []
    url = f"https://cdn.jwplayer.com/v2/media/{media_id}"
    try:
        client = HttpClient(headers={"User-Agent": get_random_user_agent()}, timeout=REQUEST_TIMEOUT, retries=3)
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
        playlist = data.get("playlist") or []
        if not playlist:
            return []
        return playlist[0].get("sources") or []
    except Exception:
        return []
    finally:
        try:
            client.close()
        except Exception:
            pass


def _fetch_jwplayer_sources(playback_url: str) -> List[dict]:
    if not playback_url:
        return []
    try:
        client = HttpClient(headers={"User-Agent": get_random_user_agent()}, timeout=REQUEST_TIMEOUT, retries=3)
        resp = client.get(playback_url)
        resp.raise_for_status()
        data = resp.json()
        playlist = data.get("playlist") or []
        if not playlist:
            return []
        return playlist[0].get("sources") or []
    except Exception:
        return []
    finally:
        try:
            client.close()
        except Exception:
            pass


def _pick_best_mp4(sources: List[dict]) -> Optional[dict]:
    mp4s = [s for s in sources if s.get("type") == "video/mp4" and s.get("file")]
    if not mp4s:
        return None
    return max(mp4s, key=lambda s: s.get("width") or s.get("bitrate") or 0)


def _download_video(url: str, output_path: str, logger: Optional[ScraperLogger] = None) -> Optional[str]:
    if not url:
        return None
    try:
        if os.path.exists(output_path):
            return output_path
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        headers = {"User-Agent": get_random_user_agent()}
        return download_to_file(
            url,
            output_path,
            headers=headers,
            timeout=VIDEO_DOWNLOAD_TIMEOUT,
            retries=3,
            backoff_base=1,
            backoff_max=10,
        )
    except Exception as exc:
        if logger:
            logger.warning(f"Error descargando video: {exc}")
        return None


def _fetch_post_by_id(post_id: int, logger: Optional[ScraperLogger]) -> Optional[dict]:
    headers = {"User-Agent": get_random_user_agent()}
    url = f"{POSTS_ENDPOINT}/{post_id}"
    params = {"_embed": "1"}
    client = HttpClient(headers=headers, timeout=REQUEST_TIMEOUT, retries=3, backoff_base=1, backoff_max=10)
    try:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        if logger:
            logger.warning(f"Error fetching post {post_id}: {exc}")
        return None
    finally:
        client.close()


def _fetch_post_by_slug(slug: str, logger: Optional[ScraperLogger]) -> Optional[dict]:
    headers = {"User-Agent": get_random_user_agent()}
    params = {"slug": slug, "_embed": "1"}
    client = HttpClient(headers=headers, timeout=REQUEST_TIMEOUT, retries=3, backoff_base=1, backoff_max=10)
    try:
        resp = client.get(POSTS_ENDPOINT, params=params)
        resp.raise_for_status()
        data = resp.json()
        if data:
            return data[0]
    except Exception as exc:
        if logger:
            logger.warning(f"Error fetching slug {slug}: {exc}")
    finally:
        client.close()
    return None


def _slug_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        parts = [p for p in parsed.path.split("/") if p]
        if parts:
            return parts[-1]
    except Exception:
        pass
    return ""


def _fetch_page_html(url: str, logger: Optional[ScraperLogger] = None) -> Optional[str]:
    try:
        html_map = fetch_html_map([url], logger=logger)
        return html_map.get(url)
    except Exception as exc:
        if logger:
            logger.warning(f"Error fetching HTML {url}: {exc}")
        return None


def _extract_paragraphs(html_content: str, extracto: str, titulo: str) -> List[str]:
    sel = Selector(text=html_content or "")
    paragraphs: List[str] = []
    seen = set()

    if extracto:
        paragraphs.append(extracto)
        seen.add(extracto)

    for element in sel.xpath("//p | //h2 | //h3 | //h4 | //li | //blockquote"):
        cls = " ".join(element.attrib.get("class", "").split())
        if re.search(r"mt-box|related|share|newsletter|ad|ads", cls, re.I):
            continue
        text = element.xpath("string(.)").get()
        text = _strip_html(text or "")
        if not text or text == titulo or text in seen:
            continue
        if element.root.tag == "p" and _is_excluded_text(text):
            continue
        paragraphs.append(text)
        seen.add(text)

    return paragraphs


def scrap_noticia_paparazzi(
    url: str,
    carpeta_imagenes: Optional[str] = None,
    logger: Optional[ScraperLogger] = None,
    post_id: Optional[int] = None,
    page_html: Optional[str] = None,
) -> Dict:
    logger = logger or ScraperLogger("PaparazziNews")
    carpeta_imagenes = carpeta_imagenes or str(FOTOS_PATH)

    post = None
    if post_id:
        post = _fetch_post_by_id(post_id, logger)
    if not post and url:
        slug = _slug_from_url(url)
        if slug:
            post = _fetch_post_by_slug(slug, logger)

    if not post:
        logger.error(f"No se pudo obtener el post: {url}")
        return {
            "titulo": "",
            "extracto": "",
            "url": url,
            "slug": "",
            "imagen": None,
            "imagen_optimizada": None,
            "imagenes_secundarias": [],
            "imagenes_url": [],
            "parrafos": [],
            "videos_url": [],
            "videos_locales": [],
            "fecha_publicacion": None,
            "fecha_texto": None,
            "fecha_scraping": datetime.now().isoformat(),
        }

    titulo = _strip_html(post.get("title", {}).get("rendered", "")) or "Sin titulo"
    extracto = _strip_html(post.get("excerpt", {}).get("rendered", ""))
    content_html = post.get("content", {}).get("rendered", "")
    link = post.get("link") or url
    slug = post.get("slug") or _sanitize_filename(titulo)

    fecha_publicacion = post.get("date")
    fecha_texto = None
    if fecha_publicacion:
        try:
            fecha_dt = datetime.fromisoformat(fecha_publicacion)
            fecha_texto = fecha_dt.strftime("%d/%m/%Y")
        except Exception:
            fecha_texto = fecha_publicacion

    imagenes_url: List[str] = []
    embedded = post.get("_embedded", {})
    if embedded.get("wp:featuredmedia"):
        featured = embedded["wp:featuredmedia"][0]
        featured_url = featured.get("source_url")
        if featured_url:
            imagenes_url = [featured_url]

    if not imagenes_url:
        imagenes_url.extend(_extract_images_from_html(content_html))

    deduped = []
    seen = set()
    for img in imagenes_url:
        if img and img not in seen:
            seen.add(img)
            deduped.append(img)
    imagenes_url = deduped

    videos_url = _extract_videos_from_html(content_html)

    if not page_html:
        page_html = _fetch_page_html(link, logger=logger)
    jwplayer_scripts = _find_jwplayer_scripts(page_html or "")
    jwplayer_videos: List[Tuple[str, dict]] = []
    for script_url in jwplayer_scripts:
        playback_url = _extract_jwplayer_playback_url(script_url)
        sources = _fetch_jwplayer_sources(playback_url)
        if not sources:
            media_id = _extract_jwplayer_media_id(script_url)
            sources = _fetch_jwplayer_v2_media(media_id)
        best = _pick_best_mp4(sources)
        if best and best.get("file"):
            jwplayer_videos.append((best["file"], best))

    for video_url, _meta in jwplayer_videos:
        if video_url not in videos_url:
            videos_url.append(video_url)

    videos_locales = []
    for idx, (video_url, meta) in enumerate(jwplayer_videos):
        label = meta.get("label") or meta.get("width") or "video"
        safe_label = _sanitize_filename(str(label))
        filename = f"{_sanitize_filename(slug)}_{idx}_{safe_label}.mp4"
        output_path = str(VIDEOS_PATH / filename)
        local_path = _download_video(video_url, output_path, logger=logger)
        if local_path:
            videos_locales.append(local_path)

    imagenes_secundarias = []
    for idx, img_url in enumerate(imagenes_url):
        original_path = None
        optimized_path = None
        filename_base = _sanitize_filename(f"{slug}_{idx}")
        original_filename = f"{filename_base}_original.jpg"
        optimized_filename = f"{filename_base}_optimized.jpg"

        try:
            original_path = process_image(img_url, original_filename, carpeta_imagenes)
            if original_path:
                optimized_path = optimize_image(original_path, optimized_filename, carpeta_imagenes)
        except Exception as exc:
            logger.warning(f"Error procesando imagen {idx}: {exc}")

        imagenes_secundarias.append({
            "original": original_path,
            "optimizada": optimized_path,
            "url": img_url,
        })

    imagen_principal = imagenes_secundarias[0]["original"] if imagenes_secundarias else None
    imagen_principal_opt = imagenes_secundarias[0]["optimizada"] if imagenes_secundarias else None

    parrafos = _extract_paragraphs(content_html, extracto, titulo)

    categorias = []
    tags = []
    if embedded.get("wp:term"):
        for term_group in embedded.get("wp:term", []):
            for term in term_group:
                if term.get("taxonomy") == "category":
                    categorias.append({"id": term.get("id"), "slug": term.get("slug"), "name": term.get("name")})
                if term.get("taxonomy") == "post_tag":
                    tags.append({"id": term.get("id"), "slug": term.get("slug"), "name": term.get("name")})

    return {
        "titulo": titulo,
        "extracto": extracto,
        "url": link,
        "slug": slug,
        "imagen": imagen_principal,
        "imagen_optimizada": imagen_principal_opt,
        "imagenes_secundarias": imagenes_secundarias,
        "imagenes_url": imagenes_url,
        "parrafos": parrafos,
        "videos_url": videos_url,
        "videos_locales": videos_locales,
        "fecha_publicacion": fecha_publicacion,
        "fecha_texto": fecha_texto,
        "fecha_scraping": datetime.now().isoformat(),
        "categorias": categorias,
        "tags": tags,
    }


if __name__ == "__main__":
    log = ScraperLogger("PaparazziNewsTest", debug=True)
    sample_url = "https://www.paparazzi.com.ar/"
    result = scrap_noticia_paparazzi(sample_url, logger=log)
    log.info(f"Titulo: {result.get('titulo')}")
    log.info(f"Imagenes: {len(result.get('imagenes_url', []))}")
    log.info(f"Videos: {len(result.get('videos_url', []))}")
