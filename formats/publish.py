"""Salida de los formatos a Instagram y Facebook, sobre ``MetaGraphPublisher``.

- Historias: IG (media_type=STORIES) y FB (foto sin publicar + /photo_stories).
- Posts: imagen o carrusel en IG; en FB una foto o un post con varias fotos
  (attached_media), el mismo texto en las dos redes.
- Reels: el mismo camino que las noticias.
- Correcciones: en FB se edita el texto del post; IG no deja editar por API, asi
  que se agrega un comentario de la cuenta.

Cupo de Instagram: 100 publicaciones por API cada 24 h. Las historias y los
formatos solo salen si queda reserva para las noticias (``reserve``).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from publishers.meta_api import MetaGraphPublisher
from storage.models import Asset, FormattedPackage

LOGGER = logging.getLogger("duo.formats.publish")


@dataclass
class Outcome:
    platform: str
    post_type: str
    status: str
    media_id: str = ""
    permalink: str = ""
    error: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)


class FormatsPublisher:
    def __init__(self, publisher: MetaGraphPublisher, *, ig_reserve: int = 25) -> None:
        self.meta = publisher
        self.settings = publisher.settings
        self.ig_reserve = ig_reserve

    # -- cupo ------------------------------------------------------------------

    def ig_room(self, needed: int = 1) -> bool:
        try:
            state = self.meta.get_ig_publish_limit()
        except Exception as exc:
            LOGGER.warning("cupo de Instagram no disponible: %s", exc)
            return False
        remaining = state.get("remaining")
        return remaining is None or int(remaining) - needed >= self.ig_reserve

    def ig_usage(self) -> Dict[str, Any]:
        try:
            return self.meta.get_ig_publish_limit()
        except Exception as exc:
            return {"error": str(exc)[:160]}

    # -- historias -----------------------------------------------------------------

    def story(self, path: str, *, platforms: Sequence[str] = ("instagram", "facebook")) -> List[Outcome]:
        package = FormattedPackage(content_key="story", post_type="story", caption="", assets=[Asset(kind="image", path=path)], meta={"defer_cleanup": True})
        outcomes: List[Outcome] = []
        try:
            if "instagram" in platforms and self.settings.enable_instagram:
                record = self.meta.publish_instagram_story(package)
                outcomes.append(Outcome("instagram", "story", record.status, record.platform_media_id, record.permalink, record.error_message or ""))
            if "facebook" in platforms and self.settings.enable_facebook:
                outcomes.append(self._facebook_story(package))
        finally:
            self._cleanup(package)
        return outcomes

    def _facebook_story(self, package: FormattedPackage) -> Outcome:
        try:
            page_id, token = self.meta._get_fb_page_id(), self.meta._get_fb_publish_token()
            if not (page_id and token):
                return Outcome("facebook", "story", "failed", error="sin credenciales de la pagina")
            url = self.meta._asset_media_url(package.assets[0])
            photo = self.meta._request("POST", f"/{page_id}/photos", data={"url": url, "published": "false"}, access_token=token)
            result = self.meta._request("POST", f"/{page_id}/photo_stories", data={"photo_id": str(photo.get("id") or "")}, access_token=token)
            return Outcome("facebook", "story", "published", str(result.get("post_id") or photo.get("id") or ""), payload={"success": result.get("success")})
        except Exception as exc:
            return Outcome("facebook", "story", "failed", error=str(exc)[:400])

    # -- posts ----------------------------------------------------------------------

    def post(self, caption: str, images: Sequence[str], *, platforms: Sequence[str] = ("instagram", "facebook")) -> List[Outcome]:
        post_type = "carousel" if len(images) > 1 else "image"
        package = FormattedPackage(content_key="format", post_type=post_type, caption=caption, assets=[Asset(kind="image", path=p) for p in images[:10]], meta={"defer_cleanup": True})
        return self._feed(package, platforms)

    def reel(self, caption: str, video: str, *, cover: str = "", seconds: float = 0, platforms: Sequence[str] = ("instagram", "facebook")) -> List[Outcome]:
        meta: Dict[str, Any] = {"defer_cleanup": True}
        if cover:
            meta["cover_path"] = cover
        package = FormattedPackage(content_key="format", post_type="reel", caption=caption, thumbnail_path=cover, assets=[Asset(kind="video", path=video, duration_seconds=seconds or None)], meta=meta)
        return self._feed(package, platforms)

    def _feed(self, package: FormattedPackage, platforms: Sequence[str]) -> List[Outcome]:
        outcomes: List[Outcome] = []
        try:
            if "instagram" in platforms and self.settings.enable_instagram:
                record = self.meta.publish_instagram(package)
                outcomes.append(Outcome("instagram", package.post_type, record.status, record.platform_media_id, record.permalink, record.error_message or ""))
            if "facebook" in platforms and self.settings.enable_facebook:
                if package.post_type == "carousel":
                    outcomes.append(self._facebook_multi_photo(package))
                else:
                    record = self.meta.publish_facebook(package)
                    outcomes.append(Outcome("facebook", package.post_type, record.status, record.platform_post_id, record.permalink, record.error_message or ""))
        finally:
            self._cleanup(package)
        return outcomes

    def _facebook_multi_photo(self, package: FormattedPackage) -> Outcome:
        """Un post de FB con todas las fotos (la API de paginas no tiene carrusel de imagenes)."""
        try:
            page_id, token = self.meta._get_fb_page_id(), self.meta._get_fb_publish_token()
            if not (page_id and token):
                return Outcome("facebook", "carousel", "failed", error="sin credenciales de la pagina")
            data: Dict[str, Any] = {"message": package.caption}
            for i, asset in enumerate(package.assets):
                url = self.meta._asset_media_url(asset)
                photo = self.meta._request("POST", f"/{page_id}/photos", data={"url": url, "published": "false"}, access_token=token)
                data[f"attached_media[{i}]"] = '{"media_fbid":"%s"}' % photo.get("id")
            result = self.meta._request("POST", f"/{page_id}/feed", data=data, access_token=token)
            return Outcome("facebook", "carousel", "published", str(result.get("id") or ""))
        except Exception as exc:
            return Outcome("facebook", "carousel", "failed", error=str(exc)[:400])

    # -- correcciones -------------------------------------------------------------------

    def facebook_edit(self, post_id: str, message: str, *, video: bool = False) -> Outcome:
        try:
            token = self.meta._get_fb_publish_token()
            field_name = "description" if video else "message"
            self.meta._request("POST", f"/{post_id}", data={field_name: message}, access_token=token)
            return Outcome("facebook", "edit", "published", post_id)
        except Exception as exc:
            return Outcome("facebook", "edit", "failed", post_id, error=str(exc)[:400])

    def instagram_comment(self, media_id: str, message: str) -> Outcome:
        try:
            result = self.meta._request("POST", f"/{media_id}/comments", data={"message": message}, access_token=self.settings.ig_access_token)
            return Outcome("instagram", "comment", "published", str(result.get("id") or ""), payload={"on": media_id})
        except Exception as exc:
            return Outcome("instagram", "comment", "failed", error=str(exc)[:400])

    def reply_comment(self, platform: str, comment_id: str, message: str) -> Outcome:
        results = self.meta.reply_comments(platform, [comment_id], message)
        if results and results[0].get("replied"):
            return Outcome(platform, "reply", "published", str(results[0].get("reply_id") or ""))
        return Outcome(platform, "reply", "failed", error=str((results[0] if results else {}).get("reason") or "sin respuesta")[:400])

    def _cleanup(self, package: FormattedPackage) -> None:
        try:
            package.meta.pop("defer_cleanup", None)
            self.meta.cleanup_package_assets(package)
        except Exception:
            pass
