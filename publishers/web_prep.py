"""Preparacion de articulos para la futura web de DUO (sin publicar nada).

Cada pieza publicada en redes deja un articulo listo en ``web_articles``, armado
con lo que el pipeline ya tiene (sin scraping extra ni otra llamada a Gemini),
siguiendo el modelo que usa La Voz Riojana para su CMS (titulo, bajada, cuerpo,
categoria, tags, imagen principal, video, fuentes, campos SEO, slug estable):

- ``event_key`` es la clave del articulo: un acontecimiento = un articulo; las
  actualizaciones reescriben el mismo registro (sirve para "Segui esta historia").
- ``slug``: titulo normalizado + sufijo corto del event_key (estable y unico).
- ``status``: ``prepared``. La entrega real queda apagada: ``ENABLE_DUO_WEB=false``
  y ``DUO_WEB_MODE=disabled`` (``publishers/duo_web.py``). No hay dominio ni CMS
  definitivos todavia, por eso aca no se inventa ninguno.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Dict, List, Optional

from editorial.captions import fix_title
from storage.editorial_config import EditorialConfig

SEO_TITLE_MAX = 60
SEO_DESCRIPTION_MAX = 155


def slugify(text: str, max_words: int = 12) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii").lower()
    words = re.findall(r"[a-z0-9]+", normalized)
    return "-".join(words[:max_words]) or "nota"


def _trim(text: str, limit: int) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(clean) <= limit:
        return clean
    return clean[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def build_web_article(row: Dict[str, Any], editorial: Dict[str, Any], formatted: Dict[str, Any], config: EditorialConfig) -> Dict[str, Any]:
    event_key = str(row.get("event_key") or row.get("content_key") or "")
    title = fix_title(str(editorial.get("hook") or row.get("title") or ""), max_chars=120)
    summary = str(row.get("summary") or "").strip()
    paragraphs: List[str] = [p.strip() for p in str(row.get("body_text") or "").splitlines() if p.strip()]
    visual = ((editorial.get("raw_response") or {}).get("visual") or {}) if isinstance(editorial.get("raw_response"), dict) else {}
    category = str(visual.get("categoria") or "actualidad")
    images: List[str] = []
    video: Optional[Dict[str, Any]] = None
    try:
        assets = json.loads(str(row.get("assets_json") or "[]"))
    except ValueError:
        assets = []
    for asset in assets if isinstance(assets, list) else []:
        if not isinstance(asset, dict):
            continue
        if asset.get("kind") == "image" and asset.get("remote_url"):
            images.append(str(asset["remote_url"]))
        if asset.get("kind") == "video" and video is None and asset.get("remote_url"):
            video = {"url": asset["remote_url"], "kind": (asset.get("meta") or {}).get("video_kind"), "duration": asset.get("duration_seconds")}
    slug = f"{slugify(title)}-{event_key.split(':')[-1][:6]}"
    return {
        "event_key": event_key,
        "content_key": str(row.get("content_key") or ""),
        "slug": slug,
        "title": title,
        "seo_title": _trim(title, SEO_TITLE_MAX),
        "seo_description": _trim(summary or (paragraphs[0] if paragraphs else title), SEO_DESCRIPTION_MAX),
        "excerpt": summary,
        "body_json": json.dumps(paragraphs, ensure_ascii=False),
        "category": category,
        "tags_json": json.dumps(re.findall(r"#\w+", str(editorial.get("caption") or ""))[1:], ensure_ascii=False),
        "main_image": images[0] if images else str(formatted.get("thumbnail_path") or ""),
        "video_json": json.dumps(video, ensure_ascii=False) if video else None,
        "sources_json": json.dumps(
            [{"name": config.display_name(row.get("source")), "url": str(row.get("canonical_url") or "")}],
            ensure_ascii=False,
        ),
        "social_caption": str(editorial.get("caption") or ""),
        "status": "prepared",
    }
