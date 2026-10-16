from __future__ import annotations

import json
import os
import re
import shutil
import unicodedata
from html import unescape
from pathlib import Path
from typing import Dict, List
import cv2
import httpx
from PIL import Image, ImageDraw
from bs4 import BeautifulSoup

from storage.models import Asset, FormattedPackage
from storage.settings import PipelineSettings, get_settings
from utils.image_processor import (
    normalize_for_instagram_carousel_secondary,
    normalize_for_instagram_pink_card,
    normalize_for_instagram_premium_card,
    normalize_for_instagram_premium_secondary,
    normalize_for_instagram_premium_v2_card,
    normalize_for_instagram_premium_v2_secondary,
    process_image,
)
from utils.instagram_carousel_slices import build_raw_news_text, create_instagram_carousel_from_news
from utils.video_processor import download_video_if_needed, process_video_for_instagram


class AssetFormatter:
    def __init__(self, settings: PipelineSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.formatted_video_dir.mkdir(parents=True, exist_ok=True)
        self.settings.formatted_image_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir = self.settings.data_dir / "ig_tmp"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir = self.settings.base_dir / "media"
        self._article_image_cache: Dict[str, List[str]] = {}

        self.target_size = (1080, 1350)
        self.watermark_path = self._resolve_path(
            os.getenv("IG_WATERMARK_PATH", str(self.media_dir / "logo.png"))
        )
        self.square_logo_path = self._resolve_path(
            os.getenv("IG_SQUARE_LOGO_PATH", str(self.settings.data_dir / "logo_cuadrado.png"))
        )
        self.footer_logo_path = self._resolve_path(
            os.getenv("IG_FOOTER_LOGO_PATH", str(self.settings.data_dir / "www.HolaSalta.com.png"))
        )
        self.slide_icon_path = self._resolve_path(
            os.getenv("IG_SLIDE_ICON_PATH", str(self.settings.data_dir / "icono_deslizar.png"))
        )
        self.overlay_template_path = self._resolve_path(
            os.getenv("IG_OVERLAY_TEMPLATE_PATH", str(self.media_dir / "PlantillaOverlay.png"))
        )
        self.title_font_path = self._resolve_path(
            os.getenv("IG_TITLE_FONT_PATH", str(self.media_dir / "Montserrat-ExtraBold.ttf"))
        )
        self.title_color = self._parse_rgb(os.getenv("IG_TITLE_COLOR", "255,255,255"), (255, 255, 255))
        self.title_shadow_color = self._parse_rgb(
            os.getenv("IG_TITLE_SHADOW_COLOR", "0,0,0"),
            (0, 0, 0),
        )
        self.title_shadow_offset = self._parse_offset(
            os.getenv("IG_TITLE_SHADOW_OFFSET", "0,3"),
            (0, 3),
        )
        self.image_layout_style = self._normalize_image_layout_style(os.getenv("IG_IMAGE_LAYOUT_STYLE", "premium_v2"))
        self.video_subtitles = os.getenv("IG_VIDEO_SUBTITLES", "0") == "1"
        self.video_quality = os.getenv("IG_VIDEO_QUALITY", "normal")
        self.video_use_layout = os.getenv("IG_VIDEO_USE_LAYOUT", "1").strip().lower() not in {"0", "false", "no", "off"}
        self.video_template_path = self._resolve_path(
            os.getenv(
                "IG_VIDEO_TEMPLATE_PATH",
                str(self.settings.base_dir / "video_app" / "assets" / "templates" / "hola_salta.json"),
            )
        )

    def format_row(self, row: Dict[str, object], *, dry_run: bool = False) -> FormattedPackage:
        editorial = self._load_json(row.get("editorial_json"))
        assets = self._load_assets(row.get("assets_json"))
        raw_payload = self._load_json(row.get("raw_payload_json"))
        content_key = str(row.get("content_key") or "")
        caption = str(editorial.get("caption") or row.get("summary") or "").strip()
        if dry_run:
            package = self._format_dry_run(content_key, row=row, assets=assets, editorial=editorial, caption=caption)
            self._validate_package(package, dry_run=True)
            return package
        if any(asset.kind == "video" for asset in assets):
            try:
                package = self._format_video(content_key, row=row, assets=assets, editorial=editorial, caption=caption)
            except RuntimeError as exc:
                has_image_fallback = any(asset.kind == "image" for asset in assets)
                source_type = str(row.get("source_type") or "").lower().strip()
                if "no tiene video local o descargable" not in str(exc) or not has_image_fallback or source_type == "x_video":
                    raise
                package = self._format_image(
                    content_key,
                    row=row,
                    assets=assets,
                    editorial=editorial,
                    raw_payload=raw_payload,
                    caption=caption,
                )
        else:
            package = self._format_image(
                content_key,
                row=row,
                assets=assets,
                editorial=editorial,
                raw_payload=raw_payload,
                caption=caption,
            )
        self._validate_package(package, dry_run=False)
        return package

    def _format_dry_run(
        self,
        content_key: str,
        *,
        row: Dict[str, object],
        assets: List[Asset],
        editorial: Dict[str, object],
        caption: str,
    ) -> FormattedPackage:
        post_type = "reel" if any(asset.kind == "video" for asset in assets) else ("carousel" if len(assets) > 1 else "image")
        return FormattedPackage(
            content_key=content_key,
            post_type=post_type,
            caption=caption,
            thumbnail_path=next((asset.path for asset in assets if asset.path), ""),
            assets=assets[:10],
            meta={
                "dry_run": True,
                "overlay": editorial.get("overlay"),
                "source_media_type": row.get("media_type"),
                "style": "dry_run_no_media_processing",
            },
        )

    def _format_video(
        self,
        content_key: str,
        *,
        row: Dict[str, object],
        assets: List[Asset],
        editorial: Dict[str, object],
        caption: str,
    ) -> FormattedPackage:
        source = next(asset for asset in assets if asset.kind == "video")
        source_ref = source.path or source.remote_url
        local_input = source.path or download_video_if_needed(source_ref, content_key, 0)
        if not local_input:
            raise RuntimeError(f"{content_key} no tiene video local o descargable")
        layout_template = self.video_template_path if self.video_use_layout and self._exists(self.video_template_path) else None
        if self.video_use_layout and not layout_template:
            raise RuntimeError(f"{content_key} no encuentra plantilla de layout de video: {self.video_template_path}")
        output_path = self.settings.formatted_video_dir / f"{content_key}_reel.mp4"
        final_path = process_video_for_instagram(
            local_input,
            str(output_path),
            template_path=layout_template,
            enable_subtitles=self.video_subtitles,
            quality=self.video_quality,
            title_text=str(editorial.get("overlay") or editorial.get("hook") or "").strip() or None,
            output_mode="reel",
        )
        thumbnail_path = self._render_thumbnail(final_path, self.settings.formatted_video_dir / f"{content_key}_thumb.jpg")
        return FormattedPackage(
            content_key=content_key,
            post_type="reel",
            caption=caption,
            thumbnail_path=thumbnail_path,
            assets=[
                Asset(
                    kind="video",
                    path=final_path,
                    duration_seconds=source.duration_seconds,
                    meta={"role": "publish"},
                )
            ],
            meta={
                "overlay": editorial.get("overlay"),
                "source_media_type": row.get("media_type"),
                "style": "legacy_video_formatter",
                "layout_template": layout_template or "",
            },
        )

    def _format_image(
        self,
        content_key: str,
        *,
        row: Dict[str, object],
        assets: List[Asset],
        editorial: Dict[str, object],
        raw_payload: Dict[str, object],
        caption: str,
    ) -> FormattedPackage:
        image_assets = [asset for asset in assets if asset.kind == "image"]
        if not image_assets:
            raise RuntimeError(f"{content_key} no tiene imagen para formatear")

        source = str(row.get("source") or "").lower().strip()
        title_text = self._title_for_visual(editorial, row, raw_payload)
        visual_theme = self._visual_theme_for_row(row, raw_payload=raw_payload, title_text=title_text)
        kicker_text = self._visual_kicker_for_theme(visual_theme)
        local_images: List[str] = []
        image_errors: List[str] = []
        for index, asset in enumerate(image_assets):
            try:
                local_images.append(
                    self._ensure_local_image(
                        asset,
                        content_key,
                        index,
                        row=row,
                        raw_payload=raw_payload,
                    )
                )
            except RuntimeError as exc:
                image_errors.append(str(exc))
        if not local_images:
            if image_errors:
                raise RuntimeError("; ".join(image_errors[:3]))
            raise RuntimeError(f"{content_key} no pudo preparar imagen fuente")

        if source == "noticiasargentinas":
            publish_assets = self._format_noticias_arg_carousel(
                content_key,
                local_images=local_images,
                title_text=title_text,
                visual_theme=visual_theme,
                kicker_text=kicker_text,
                raw_payload=raw_payload,
                row=row,
            )
        else:
            publish_assets = self._format_standard_image_set(
                content_key,
                local_images=local_images,
                title_text=title_text,
                visual_theme=visual_theme,
                kicker_text=kicker_text,
            )

        post_type = "carousel" if len(publish_assets) > 1 else "image"
        thumbnail_path = publish_assets[0].path if publish_assets else ""
        return FormattedPackage(
            content_key=content_key,
            post_type=post_type,
            caption=caption,
            thumbnail_path=thumbnail_path,
            assets=publish_assets,
            meta={
                "overlay": editorial.get("overlay"),
                "source_media_type": row.get("media_type"),
                "style": self._image_formatter_style(),
                "visual_theme": visual_theme,
            },
        )

    def _format_standard_image_set(
        self,
        content_key: str,
        *,
        local_images: List[str],
        title_text: str,
        visual_theme: str,
        kicker_text: str,
    ) -> List[Asset]:
        overlay_images: List[str] = []
        has_multiple = len(local_images) > 1
        for index, local_image in enumerate(local_images):
            output_name = f"{content_key}_{index:02d}.jpg"
            if index == 0:
                if self.image_layout_style == "legacy":
                    result = normalize_for_instagram_pink_card(
                        local_image,
                        output_filename=output_name,
                        folder=str(self.settings.formatted_image_dir),
                        target_size=self.target_size,
                        corner_logo_path=self.square_logo_path if self._exists(self.square_logo_path) else None,
                        slide_icon_path=self.slide_icon_path if has_multiple and self._exists(self.slide_icon_path) else None,
                        center_logo_path=self.watermark_path if self._exists(self.watermark_path) else None,
                        footer_logo_path=self.footer_logo_path if self._exists(self.footer_logo_path) else None,
                        title_text=title_text,
                        title_font_path=self.title_font_path if self._exists(self.title_font_path) else None,
                        title_color=self.title_color,
                        title_shadow_color=self.title_shadow_color,
                        title_shadow_offset=self.title_shadow_offset,
                        overlay_template_path=self.overlay_template_path if self._exists(self.overlay_template_path) else None,
                    )
                elif self.image_layout_style == "premium":
                    result = normalize_for_instagram_premium_card(
                        local_image,
                        output_filename=output_name,
                        folder=str(self.settings.formatted_image_dir),
                        target_size=self.target_size,
                        title_text=title_text,
                        title_font_path=self.title_font_path if self._exists(self.title_font_path) else None,
                        title_color=self.title_color,
                        title_shadow_color=self.title_shadow_color,
                        title_shadow_offset=(0, 2),
                        overlay_template_path=self.overlay_template_path if self._exists(self.overlay_template_path) else None,
                    )
                else:
                    result = normalize_for_instagram_premium_v2_card(
                        local_image,
                        output_filename=output_name,
                        folder=str(self.settings.formatted_image_dir),
                        target_size=self.target_size,
                        title_text=title_text,
                        kicker_text=kicker_text,
                        content_theme=visual_theme,
                        title_font_path=self.title_font_path if self._exists(self.title_font_path) else None,
                        title_color=self.title_color,
                        title_shadow_color=self.title_shadow_color,
                        overlay_template_path=self.overlay_template_path if self._exists(self.overlay_template_path) else None,
                    )
            else:
                if self.image_layout_style == "legacy":
                    result = normalize_for_instagram_carousel_secondary(
                        local_image,
                        output_filename=output_name,
                        folder=str(self.settings.formatted_image_dir),
                        target_size=self.target_size,
                        corner_logo_path=self.square_logo_path if self._exists(self.square_logo_path) else None,
                        bottom_logo_path=self.watermark_path if self._exists(self.watermark_path) else None,
                        overlay_template_path=self.overlay_template_path if self._exists(self.overlay_template_path) else None,
                    )
                elif self.image_layout_style == "premium":
                    result = normalize_for_instagram_premium_secondary(
                        local_image,
                        output_filename=output_name,
                        folder=str(self.settings.formatted_image_dir),
                        target_size=self.target_size,
                        overlay_template_path=self.overlay_template_path if self._exists(self.overlay_template_path) else None,
                    )
                else:
                    result = normalize_for_instagram_premium_v2_secondary(
                        local_image,
                        output_filename=output_name,
                        folder=str(self.settings.formatted_image_dir),
                        target_size=self.target_size,
                        content_theme=visual_theme,
                        title_font_path=self.title_font_path if self._exists(self.title_font_path) else None,
                        overlay_template_path=self.overlay_template_path if self._exists(self.overlay_template_path) else None,
                    )
            if result and Path(result).exists():
                overlay_images.append(result)

        if not overlay_images:
            raise RuntimeError(f"{content_key} no genero imagenes finales")

        return [
            Asset(
                kind="image",
                path=path,
                meta={"role": "cover" if index == 0 else "carousel"},
            )
            for index, path in enumerate(overlay_images)
        ]

    def _format_noticias_arg_carousel(
        self,
        content_key: str,
        *,
        local_images: List[str],
        title_text: str,
        visual_theme: str,
        kicker_text: str,
        raw_payload: Dict[str, object],
        row: Dict[str, object],
    ) -> List[Asset]:
        primary = self._prepare_na_source_with_black_box(local_images[0], content_key)
        if self.image_layout_style == "legacy":
            cover_path = normalize_for_instagram_pink_card(
                primary,
                output_filename=f"{content_key}_00.jpg",
                folder=str(self.settings.formatted_image_dir),
                target_size=self.target_size,
                corner_logo_path=self.square_logo_path if self._exists(self.square_logo_path) else None,
                slide_icon_path=self.slide_icon_path if self._exists(self.slide_icon_path) else None,
                center_logo_path=self.watermark_path if self._exists(self.watermark_path) else None,
                footer_logo_path=self.footer_logo_path if self._exists(self.footer_logo_path) else None,
                title_text=title_text,
                title_font_path=self.title_font_path if self._exists(self.title_font_path) else None,
                title_color=self.title_color,
                title_shadow_color=self.title_shadow_color,
                title_shadow_offset=self.title_shadow_offset,
                overlay_template_path=self.overlay_template_path if self._exists(self.overlay_template_path) else None,
            )
        elif self.image_layout_style == "premium":
            cover_path = normalize_for_instagram_premium_card(
                primary,
                output_filename=f"{content_key}_00.jpg",
                folder=str(self.settings.formatted_image_dir),
                target_size=self.target_size,
                title_text=title_text,
                title_font_path=self.title_font_path if self._exists(self.title_font_path) else None,
                title_color=self.title_color,
                title_shadow_color=self.title_shadow_color,
                title_shadow_offset=(0, 2),
                overlay_template_path=self.overlay_template_path if self._exists(self.overlay_template_path) else None,
            )
        else:
            cover_path = normalize_for_instagram_premium_v2_card(
                primary,
                output_filename=f"{content_key}_00.jpg",
                folder=str(self.settings.formatted_image_dir),
                target_size=self.target_size,
                title_text=title_text,
                kicker_text=kicker_text,
                content_theme=visual_theme,
                title_font_path=self.title_font_path if self._exists(self.title_font_path) else None,
                title_color=self.title_color,
                title_shadow_color=self.title_shadow_color,
                overlay_template_path=self.overlay_template_path if self._exists(self.overlay_template_path) else None,
            )
        if not cover_path or not Path(cover_path).exists():
            raise RuntimeError(f"{content_key} no genero portada NA")

        news_payload = raw_payload if raw_payload else self._fallback_news_payload(row)
        raw_news_text = build_raw_news_text(news_payload)
        carousel_paths = create_instagram_carousel_from_news(
            cover_path,
            raw_news_text,
            str(self.settings.formatted_image_dir),
            content_key,
        )
        if not carousel_paths:
            raise RuntimeError(f"{content_key} no genero carrusel NA")
        return [
            Asset(
                kind="image",
                path=path,
                meta={"role": "cover" if index == 0 else "carousel"},
            )
            for index, path in enumerate(carousel_paths)
        ]

    def _ensure_local_image(
        self,
        asset: Asset,
        content_key: str,
        index: int,
        *,
        row: Dict[str, object] | None = None,
        raw_payload: Dict[str, object] | None = None,
    ) -> str:
        if asset.path:
            return asset.path
        filename = f"{content_key}_{index}_source.jpg"
        for candidate in self._image_download_candidates(asset, row=row or {}, raw_payload=raw_payload or {}):
            local = process_image(candidate, filename, str(self.temp_dir))
            if local:
                return str(local)
        if self._requires_real_source_image(row or {}, raw_payload or {}):
            raise RuntimeError(f"{content_key} no pudo descargar imagen fuente real")
        return self._create_fallback_source_image(content_key, index)

    def _create_fallback_source_image(self, content_key: str, index: int) -> str:
        output = self.temp_dir / f"{content_key}_{index}_fallback.jpg"
        width, height = self.target_size
        image = Image.new("RGB", (width, height), (26, 28, 32))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, width, 18), fill=(237, 40, 94))
        draw.rectangle((0, height - 22, width, height), fill=(237, 40, 94))
        draw.rectangle((70, 120, width - 70, height - 120), outline=(70, 76, 88), width=4)
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output, format="JPEG", quality=94)
        return str(output)

    def _image_download_candidates(
        self,
        asset: Asset,
        *,
        row: Dict[str, object],
        raw_payload: Dict[str, object],
    ) -> List[str]:
        candidates: List[str] = []
        seen: set[str] = set()

        def push(value: object) -> None:
            raw = unescape(str(value or "")).strip()
            if not raw or raw in seen:
                return
            seen.add(raw)
            candidates.append(raw)

        article_url = str(row.get("canonical_url") or raw_payload.get("url") or "").strip()
        for candidate in self._discover_article_image_candidates(article_url):
            push(candidate)
        push(asset.remote_url)
        for item in raw_payload.get("image_urls") or []:
            push(item)
        for key in ("image", "image_url", "thumbnail", "thumbnail_url", "og_image", "hero_image"):
            push(raw_payload.get(key))
        return candidates

    def _discover_article_image_candidates(self, article_url: str) -> List[str]:
        url = str(article_url or "").strip()
        if not url.startswith(("http://", "https://")):
            return []
        cached = self._article_image_cache.get(url)
        if cached is not None:
            return list(cached)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
        }
        candidates: List[str] = []
        seen: set[str] = set()

        def push(value: object) -> None:
            raw = unescape(str(value or "")).strip()
            if not raw or raw in seen:
                return
            seen.add(raw)
            candidates.append(raw)

        try:
            response = httpx.get(
                url,
                headers=headers,
                follow_redirects=True,
                timeout=20.0,
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            for attrs in (
                {"property": "og:image"},
                {"property": "og:image:secure_url"},
                {"name": "twitter:image"},
                {"name": "twitter:image:src"},
            ):
                tag = soup.find("meta", attrs=attrs)
                if tag:
                    push(tag.get("content"))
            for match in re.findall(r'"thumbnailUrl":"([^"]+)"', response.text):
                push(match.replace("\\/", "/"))
        except Exception:
            candidates = []

        self._article_image_cache[url] = list(candidates)
        return candidates

    @staticmethod
    def _requires_real_source_image(row: Dict[str, object], raw_payload: Dict[str, object]) -> bool:
        article_url = str(row.get("canonical_url") or raw_payload.get("url") or "").strip()
        if not article_url.startswith(("http://", "https://")):
            return False
        source_type = str(row.get("source_type") or "").strip().lower()
        if source_type:
            return source_type in {"news", "article", "rss_html"}
        return True

    @staticmethod
    def _load_json(raw: object) -> Dict[str, object]:
        try:
            payload = json.loads(str(raw or ""))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _load_assets(raw: object) -> List[Asset]:
        try:
            payload = json.loads(str(raw or "[]"))
        except Exception:
            payload = []
        assets: List[Asset] = []
        for item in payload if isinstance(payload, list) else []:
            if not isinstance(item, dict):
                continue
            assets.append(
                Asset(
                    kind=str(item.get("kind") or ""),
                    path=str(item.get("path") or ""),
                    remote_url=str(item.get("remote_url") or ""),
                    mime_type=str(item.get("mime_type") or ""),
                    duration_seconds=float(item.get("duration_seconds") or 0.0) or None,
                    sha1=str(item.get("sha1") or ""),
                    perceptual_hash=str(item.get("perceptual_hash") or ""),
                    meta=dict(item.get("meta") or {}),
                )
            )
        return assets

    @staticmethod
    def _render_thumbnail(video_path: str, output_path: Path) -> str:
        capture = cv2.VideoCapture(video_path)
        ok, frame = capture.read()
        capture.release()
        if not ok or frame is None:
            return ""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(output_path), frame)
        return str(output_path)

    @staticmethod
    def _resolve_path(value: str) -> str:
        if not value:
            return ""
        path = Path(value)
        if path.is_absolute():
            return str(path)
        return str(path.resolve())

    @staticmethod
    def _parse_rgb(value: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
        raw = (value or "").strip()
        if not raw:
            return fallback
        if raw.startswith("#"):
            raw = raw[1:]
        if "," in raw:
            try:
                parts = [int(part.strip()) for part in raw.split(",")[:3]]
                if len(parts) == 3:
                    return parts[0], parts[1], parts[2]
            except ValueError:
                return fallback
        if len(raw) == 6:
            try:
                return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
            except ValueError:
                return fallback
        return fallback

    @staticmethod
    def _parse_offset(value: str, fallback: tuple[int, int]) -> tuple[int, int]:
        raw = (value or "").strip()
        if not raw or "," not in raw:
            return fallback
        try:
            left, top = raw.split(",", 1)
            return int(left.strip()), int(top.strip())
        except ValueError:
            return fallback

    @staticmethod
    def _exists(path: str) -> bool:
        return bool(path) and Path(path).exists()

    @staticmethod
    def _normalize_image_layout_style(value: str) -> str:
        raw = (value or "premium_v2").strip().lower().replace("-", "_")
        if raw in {"legacy", "classic"}:
            return "legacy"
        if raw in {"premium", "premium_v1", "v1"}:
            return "premium"
        return "premium_v2"

    def _image_formatter_style(self) -> str:
        if self.image_layout_style == "legacy":
            return "legacy_image_formatter"
        if self.image_layout_style == "premium":
            return "premium_image_formatter"
        return "premium_v2_image_formatter"

    @staticmethod
    def _text_for_theme(value: object) -> str:
        text = unicodedata.normalize("NFKD", str(value or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        return re.sub(r"\s+", " ", text.lower())

    def _visual_theme_for_row(
        self,
        row: Dict[str, object],
        *,
        raw_payload: Dict[str, object],
        title_text: str,
    ) -> str:
        source = self._text_for_theme(row.get("source"))
        text = self._text_for_theme(
            " ".join(
                [
                    title_text,
                    str(row.get("title") or ""),
                    str(row.get("summary") or ""),
                    str(raw_payload.get("categoria") or raw_payload.get("category") or ""),
                    str(raw_payload.get("source") or ""),
                ]
            )
        )
        keyword_groups = (
            (
                "sensitive",
                (
                    "muerte",
                    "muerto",
                    "asesin",
                    "abuso",
                    "violencia",
                    "preso",
                    "carcel",
                    "crimen",
                    "baleo",
                    "accidente fatal",
                    "violacion",
                ),
            ),
            (
                "politics",
                (
                    "milei",
                    "gobierno",
                    "congreso",
                    "senado",
                    "diputado",
                    "gobernador",
                    "ministro",
                    "elecciones",
                    "nacion",
                ),
            ),
            (
                "business",
                (
                    "dolar",
                    "mercado",
                    "economia",
                    "banco",
                    "inflacion",
                    "financiero",
                    "wall street",
                    "bono",
                ),
            ),
            (
                "sports",
                (
                    "boca",
                    "river",
                    "seleccion",
                    "torneo",
                    "futbol",
                    "partido",
                    "racing",
                    "independiente",
                ),
            ),
            (
                "showbiz",
                (
                    "telefe",
                    "actriz",
                    "actor",
                    "cantante",
                    "romance",
                    "famos",
                    "reality",
                    "gran hermano",
                    "wanda",
                    "lali",
                ),
            ),
        )
        for theme, keywords in keyword_groups:
            if any(keyword in text for keyword in keywords):
                return theme
        if "paparazzi" in source:
            return "showbiz"
        return "default"

    @staticmethod
    def _visual_kicker_for_theme(theme: str) -> str:
        labels = {
            "showbiz": "ESPECTACULOS",
            "politics": "POLITICA",
            "business": "ECONOMIA",
            "sports": "DEPORTES",
            "sensitive": "INFORMACION",
        }
        return labels.get(str(theme or "").lower(), "TENDENCIA")

    @staticmethod
    def _title_for_visual(
        editorial: Dict[str, object],
        row: Dict[str, object],
        raw_payload: Dict[str, object],
    ) -> str:
        raw = (
            editorial.get("hook")
            or editorial.get("overlay")
            or raw_payload.get("titulo_instagram")
            or raw_payload.get("titulo")
            or row.get("title")
            or row.get("summary")
            or ""
        )
        clean = re.sub(r"[\U00010000-\U0010ffff]", "", str(raw))
        clean = re.sub(r"#[\w_]+", "", clean)
        return re.sub(r"\s+", " ", clean).strip()

    def _prepare_na_source_with_black_box(self, image_path: str, content_key: str) -> str:
        if not image_path or not Path(image_path).exists():
            return image_path
        ext = Path(image_path).suffix or ".jpg"
        temp_path = self.temp_dir / f"{content_key}_na_box{ext}"
        try:
            shutil.copy2(image_path, temp_path)
            self._apply_na_black_box(temp_path)
            return str(temp_path)
        except Exception:
            return image_path

    @staticmethod
    def _apply_na_black_box(image_path: Path) -> None:
        try:
            from PIL import Image, ImageDraw

            with Image.open(image_path) as base:
                if base.mode != "RGBA":
                    base = base.convert("RGBA")
                width, height = base.size
                box_w = int(width * 0.42)
                box_h = int(height * 0.18)
                draw = ImageDraw.Draw(base)
                draw.rectangle([0, height - box_h, box_w, height], fill=(0, 0, 0))
                base.convert("RGB").save(image_path, quality=95)
        except Exception:
            return

    @staticmethod
    def _fallback_news_payload(row: Dict[str, object]) -> Dict[str, object]:
        body_text = str(row.get("body_text") or "").strip()
        paragraphs = [part.strip() for part in body_text.splitlines() if part.strip()]
        return {
            "titulo": str(row.get("title") or ""),
            "extracto": str(row.get("summary") or ""),
            "parrafos": paragraphs,
            "url": str(row.get("canonical_url") or ""),
        }

    @staticmethod
    def _validate_package(package: FormattedPackage, *, dry_run: bool) -> None:
        if not package.content_key:
            raise RuntimeError("formatted package sin content_key")
        if package.post_type not in {"reel", "carousel", "image", "story"}:
            raise RuntimeError(f"{package.content_key} post_type invalido: {package.post_type}")
        if not package.assets:
            raise RuntimeError(f"{package.content_key} no tiene assets formateados")
        if package.post_type == "reel" and not any(asset.kind == "video" for asset in package.assets):
            raise RuntimeError(f"{package.content_key} reel sin video final")
        if package.post_type in {"carousel", "image"} and not any(asset.kind == "image" for asset in package.assets):
            raise RuntimeError(f"{package.content_key} post de imagen sin imagen final")
        if dry_run:
            return

        min_image_bytes = int(os.getenv("IG_MIN_IMAGE_OUTPUT_BYTES", "2048"))
        min_video_bytes = int(os.getenv("IG_MIN_VIDEO_OUTPUT_BYTES", "50000"))
        for asset in package.assets:
            if not asset.path:
                raise RuntimeError(f"{package.content_key} asset final sin path")
            path = Path(asset.path)
            if not path.exists():
                raise RuntimeError(f"{package.content_key} asset final inexistente: {path}")
            size = path.stat().st_size
            if asset.kind == "video" and size < min_video_bytes:
                raise RuntimeError(f"{package.content_key} video final demasiado chico: {size} bytes")
            if asset.kind == "image" and size < min_image_bytes:
                raise RuntimeError(f"{package.content_key} imagen final demasiado chica: {size} bytes")
