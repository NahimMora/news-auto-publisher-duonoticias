"""Scraper de noticias para Noticias Argentinas."""
from datetime import datetime
import json
import os
import re
import unicodedata
from typing import List, Tuple

from bs4 import BeautifulSoup

try:
    from utils.http_client import HttpClient
except ImportError:  # pragma: no cover
    import sys
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT))
    from utils.http_client import HttpClient

try:
    from scrapping.noticiasargentinas.config import (
        TEXT_EXCLUDE_PATTERNS,
        IMAGE_EXCLUDE_PATTERNS,
        REQUEST_TIMEOUT,
        HTTP_RETRIES,
        HTTP_BACKOFF_BASE,
        get_random_user_agent,
        NA_OVERLAY_BOX_COLOR,
        NA_OVERLAY_BOX_REL_W,
        NA_OVERLAY_BOX_REL_H,
        NA_OVERLAY_BOX_POSITION,
        NA_OVERLAY_LOGO_MARGIN,
    )
    from scrapping.noticiasargentinas.logger import ScraperLogger
except ImportError:
    from .config import (
        TEXT_EXCLUDE_PATTERNS,
        IMAGE_EXCLUDE_PATTERNS,
        REQUEST_TIMEOUT,
        HTTP_RETRIES,
        HTTP_BACKOFF_BASE,
        get_random_user_agent,
        NA_OVERLAY_BOX_COLOR,
        NA_OVERLAY_BOX_REL_W,
        NA_OVERLAY_BOX_REL_H,
        NA_OVERLAY_BOX_POSITION,
        NA_OVERLAY_LOGO_MARGIN,
    )
    from .logger import ScraperLogger


def _clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _slugify(text: str) -> str:
    if not text:
        return "noticia"
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = re.sub(r"[^\w\s-]", "", ascii_text).strip().lower()
    ascii_text = re.sub(r"[\s-]+", "_", ascii_text)
    return ascii_text or "noticia"


def _extract_date(soup: BeautifulSoup) -> Tuple[str | None, str | None]:
    time_tag = soup.find("time", datetime=True)
    if time_tag:
        return time_tag.get("datetime"), _clean_text(time_tag.get_text())

    meta_pub = soup.find("meta", property="article:published_time")
    if meta_pub and meta_pub.get("content"):
        return meta_pub.get("content"), None

    meta_date = soup.find("meta", attrs={"name": "date"})
    if meta_date and meta_date.get("content"):
        return meta_date.get("content"), None

    return None, None


def _extract_article_container(soup: BeautifulSoup):
    body = soup.find("div", class_=re.compile(r"article-body-content", re.I))
    if body:
        return body
    article = soup.find("article")
    if article:
        return article
    candidates = soup.find_all(
        "div",
        class_=re.compile(r"(article|nota|contenido|post|body|entry)", re.I),
    )
    return candidates[0] if candidates else soup


def _extract_author(soup: BeautifulSoup) -> str:
    meta_author = soup.find("meta", attrs={"name": "author"})
    if meta_author and meta_author.get("content"):
        return _clean_text(meta_author.get("content"))
    author_tag = soup.find(class_=re.compile(r"author|autor", re.I))
    if author_tag:
        return _clean_text(author_tag.get_text(" ", strip=True))
    return ""


def _extract_paragraphs(container, extracto: str) -> List[str]:
    paragraphs = []
    if not container:
        return paragraphs

    blocks = container.find_all(["p", "h2", "h3", "blockquote", "li"])
    seen = set()
    for block in blocks:
        text = _clean_text(block.get_text(" ", strip=True))
        if not text or len(text) < 8:
            continue
        if extracto and text == extracto:
            continue
        for pattern in TEXT_EXCLUDE_PATTERNS:
            text = text.replace(pattern, "")
        text = _clean_text(text)
        if not text or len(text) < 8:
            continue
        if text in seen:
            continue
        seen.add(text)
        paragraphs.append(text)

    return paragraphs


def _is_bad_url(url: str) -> bool:
    if not isinstance(url, str):
        return True
    lowered = url.lower()
    if not lowered.startswith("http"):
        return True
    for token in IMAGE_EXCLUDE_PATTERNS:
        if token in lowered:
            return True
    return False


def _extract_image_urls(container, soup: BeautifulSoup) -> Tuple[List[str], bool]:
    def _pick_srcset(srcset_value: str) -> str | None:
        if not srcset_value:
            return None
        candidates = []
        for part in srcset_value.split(","):
            chunk = part.strip().split(" ")
            if not chunk:
                continue
            url = chunk[0]
            width = 0
            if len(chunk) > 1 and chunk[1].endswith("w"):
                try:
                    width = int(chunk[1].rstrip("w"))
                except ValueError:
                    width = 0
            candidates.append((width, url))
        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0][1]

    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        return [og_image.get("content")], True

    for source in container.find_all("source", srcset=True):
        srcset_url = _pick_srcset(source.get("srcset"))
        if srcset_url and not _is_bad_url(srcset_url):
            return [srcset_url], False

    images = []
    for img in container.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        if not src or _is_bad_url(src):
            continue
        images.append(src)
        break

    # JSON-LD image candidates
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = script.string
            if not data:
                continue
            payload = json.loads(data)
        except Exception:
            continue

        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, dict):
                continue
            img_field = item.get("image") or item.get("primaryImageOfPage") or item.get("contentUrl")
            if not img_field:
                continue
            candidates = img_field if isinstance(img_field, list) else [img_field]
            for candidate in candidates:
                url = candidate.get("url") if isinstance(candidate, dict) else candidate
                if not url or _is_bad_url(url):
                    continue
                images.append(url)
                break
            if images:
                break
        if images:
            break

    return images, False


def _extract_video_urls(soup: BeautifulSoup, container: BeautifulSoup | None = None) -> List[str]:
    urls: List[str] = []
    scopes = []
    if container is not None:
        scopes.append(container)
        parent_article = container.find_parent("article")
        if parent_article:
            scopes.append(parent_article)
    if not scopes:
        scopes.append(soup)

    # Meta tags (fallback)
    for prop in ["og:video", "og:video:url", "og:video:secure_url", "twitter:player"]:
        tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        if tag and tag.get("content"):
            urls.append(tag.get("content"))

    # Direct player element used by NA
    for scope in scopes:
        for player in scope.find_all("x-player"):
            for key in ("url", "data-url", "data-src", "src"):
                src = player.get(key)
                if src:
                    urls.append(src)

    # If we already have direct player URLs, skip generic video tags to avoid related widgets.
    has_direct_player = any(u for u in urls if u.lower().split("?")[0].endswith((".mp4", ".mov", ".m4v", ".webm")))
    if not has_direct_player:
        for scope in scopes:
            # Video tags in main container, skipping related widgets
            for video in scope.find_all("video"):
                # Skip if inside related widgets/cards
                skip = False
                for parent in video.parents:
                    classes = parent.get("class") or []
                    if isinstance(classes, str):
                        classes = [classes]
                    if any(cls in ("article-related", "widget-article") for cls in classes):
                        skip = True
                        break
                if skip:
                    continue
                src = video.get("src")
                if src:
                    urls.append(src)
                for source in video.find_all("source"):
                    src = source.get("src")
                    if src:
                        urls.append(src)

    # Dedup
    seen = set()
    unique = []
    for url in urls:
        if url and url not in seen:
            seen.add(url)
            unique.append(url)

    # Prefer direct video files only
    direct = [
        u for u in unique
        if u.lower().split("?")[0].endswith((".mp4", ".mov", ".m4v", ".webm"))
    ]
    return direct


def _apply_logo_overlay(image_path):
    if not image_path or not os.path.exists(image_path):
        return
    try:
        from PIL import Image, ImageDraw

        with Image.open(image_path) as base:
            if base.mode != "RGBA":
                base = base.convert("RGBA")

            width, height = base.size
            box_w = int(width * NA_OVERLAY_BOX_REL_W)
            box_h = int(height * NA_OVERLAY_BOX_REL_H)
            margin = NA_OVERLAY_LOGO_MARGIN

            if NA_OVERLAY_BOX_POSITION == "bottom_right":
                box_x = width - box_w - margin
                box_y = height - box_h - margin
            elif NA_OVERLAY_BOX_POSITION == "top_left":
                box_x = margin
                box_y = margin
            elif NA_OVERLAY_BOX_POSITION == "top_right":
                box_x = width - box_w - margin
                box_y = margin
            else:
                box_x = margin
                box_y = height - box_h - margin

            draw = ImageDraw.Draw(base)
            draw.rectangle([box_x, box_y, box_x + box_w, box_y + box_h], fill=NA_OVERLAY_BOX_COLOR)

            base = base.convert("RGB")
            base.save(image_path, format="JPEG", quality=95)
    except Exception:
        return


def _download_images(image_urls, slug, photos_folder, overlay_logo=False):
    if not photos_folder or not image_urls:
        return None, None, [], []
    try:
        from utils.image_processor import process_image, optimize_image
    except Exception:
        return None, None, [], []

    primary = None
    primary_opt = None
    secondary = []
    urls = []

    for idx, url in enumerate(image_urls):
        if not url:
            continue
        urls.append(url)
        original_name = f"{slug}_img{idx}_original.jpg"
        optimized_name = f"{slug}_img{idx}_optimized.jpg"
        original_path = process_image(url, original_name, photos_folder)
        if original_path and overlay_logo:
            _apply_logo_overlay(original_path)
        optimized_path = None
        if original_path:
            optimized_path = optimize_image(original_path, optimized_name, photos_folder)
        if idx == 0:
            primary = original_path
            primary_opt = optimized_path
        secondary.append(
            {
                "original": original_path,
                "optimizada": optimized_path,
                "url": url,
            }
        )

    return primary, primary_opt, secondary, urls


def scrap_noticia_noticiasargentinas(url, carpeta_imagenes, logger=None):
    logger = logger or ScraperLogger("NoticiasArgentinasNews")
    headers = {"User-Agent": get_random_user_agent()}
    client = HttpClient(headers=headers, timeout=REQUEST_TIMEOUT, retries=HTTP_RETRIES, backoff_base=HTTP_BACKOFF_BASE)
    try:
        resp = client.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        titulo_tag = soup.find("h1")
        titulo = _clean_text(titulo_tag.get_text()) if titulo_tag else ""

        meta_desc = soup.find("meta", property="og:description") or soup.find(
            "meta", attrs={"name": "description"}
        )
        extracto = _clean_text(meta_desc.get("content")) if meta_desc else ""

        deck_tag = soup.find("h2", class_="article-deck")
        deck_text = _clean_text(deck_tag.get_text()) if deck_tag else ""

        fecha_publicacion, fecha_texto = _extract_date(soup)
        if fecha_publicacion and not fecha_texto:
            try:
                dt = datetime.fromisoformat(fecha_publicacion.replace("Z", "+00:00"))
                fecha_texto = dt.strftime("%d %B %Y")
            except Exception:
                pass

        autor = _extract_author(soup)
        container = _extract_article_container(soup)
        parrafos = _extract_paragraphs(container, extracto)
        if deck_text:
            if not parrafos or parrafos[0] != deck_text:
                parrafos.insert(0, deck_text)

        slug = _slugify(titulo)
        image_urls, used_og = _extract_image_urls(container, soup)
        imagen, imagen_opt, imagenes_secundarias, imagenes_url = _download_images(
            image_urls, slug, carpeta_imagenes, overlay_logo=used_og
        )

        videos_url = _extract_video_urls(soup, container)

        return {
            "titulo": titulo,
            "extracto": extracto,
            "url": url,
            "slug": slug,
            "imagen": imagen,
            "imagen_optimizada": imagen_opt,
            "imagenes_secundarias": imagenes_secundarias,
            "imagenes_url": imagenes_url,
            "videos_url": videos_url,
            "autor": autor,
            "parrafos": parrafos,
            "fecha_publicacion": fecha_publicacion,
            "fecha_texto": fecha_texto,
            "fecha_scraping": datetime.now().isoformat(),
            "source": "noticiasargentinas",
            "medio": "Noticias Argentinas",
        }

    except Exception as exc:
        logger.error(f"Error scrapeando {url}: {exc}")
        return {
            "titulo": "",
            "extracto": "",
            "url": url,
            "slug": "",
            "imagen": None,
            "imagen_optimizada": None,
            "imagenes_secundarias": [],
            "imagenes_url": [],
            "videos_url": [],
            "autor": "",
            "parrafos": [],
            "fecha_publicacion": None,
            "fecha_texto": None,
            "fecha_scraping": datetime.now().isoformat(),
            "source": "noticiasargentinas",
            "medio": "Noticias Argentinas",
        }
    finally:
        client.close()

