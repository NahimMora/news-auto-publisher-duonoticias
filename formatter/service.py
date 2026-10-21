from __future__ import annotations

import json
import logging
import os
import re
import time
import unicodedata
from html import unescape
from pathlib import Path
from typing import Dict, List
import cv2
import numpy as np
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
from formatter.motion_engine import (
    MotionEngine,
    MotionRenderError,
    MotionUnavailable,
    extract_visual,
)
from storage.editorial_config import load_editorial_config
from utils.video_processor import process_video_for_instagram
from utils.watermark import SOURCE_BRANDS, check_image

LOGGER = logging.getLogger(__name__)
# Diferencia maxima (bits de dHash 64) para considerar dos fotos la misma imagen.
DUPLICATE_HAMMING = 6


PLACEHOLDER_URL = re.compile(r"(fallback|placeholder|default[-_]?(image|img|promo)|no[-_]?image|sin[-_]?imagen|/logos?/|(?<![a-z])logo[-_.])", re.I)


def is_placeholder_image(path: str, url: str = "") -> bool:
    """Imagen generica del medio (logo sobre fondo plano: "infobae" en naranja, El Tribuno en azul).

    Calibrado 2026-10-18: las genericas usan 2-6 colores (cuantizados a 16 niveles) para cubrir el
    95 % de la imagen y un solo color ocupa >= 88 %; 160 fotos reales: >= 9 colores y <= 56 %.
    """
    if url and PLACEHOLDER_URL.search(url):
        return True
    image = cv2.imread(str(path))
    if image is None:
        return False
    thumb = cv2.resize(image, (128, 128), interpolation=cv2.INTER_AREA)
    q = (thumb // 16).reshape(-1, 3).astype(np.int32)
    _, counts = np.unique(q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2], return_counts=True)
    counts = np.sort(counts)[::-1]
    cover = int(np.searchsorted(np.cumsum(counts), 0.95 * counts.sum())) + 1
    return counts[0] / counts.sum() >= 0.7 and cover <= 8


class NoRealPhoto(RuntimeError):
    """Nota sin ninguna foto real (solo la imagen generica del medio) donde la foto es obligatoria."""


class WatermarkBlocked(RuntimeError):
    """Todas las fotos disponibles tienen marca de agua de otro medio: la pieza se descarta."""


def same_scene(path_a: str, path_b: str) -> bool:
    """Misma foto con otro recorte o escala (ORB + RANSAC): la misma imagen 16:9 y original.
    Calibrado: misma foto ~880 coincidencias geometricas; fotos distintas <= 31."""
    orb = cv2.ORB_create(1500)
    keys = []
    for path in (path_a, path_b):
        gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            return False
        gray = cv2.resize(gray, (640, max(1, int(gray.shape[0] * 640 / gray.shape[1]))), interpolation=cv2.INTER_AREA)
        keys.append(orb.detectAndCompute(gray, None))
    (ka, da), (kb, db) = keys
    if da is None or db is None or len(ka) < 20 or len(kb) < 20:
        return False
    matches = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(da, db)
    if len(matches) < 60:
        return False
    pa = np.float32([ka[m.queryIdx].pt for m in matches])
    pb = np.float32([kb[m.trainIdx].pt for m in matches])
    _, inliers = cv2.estimateAffinePartial2D(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=4)
    count = int(inliers.sum()) if inliers is not None else 0
    return count >= 60 and count >= 0.25 * len(matches)


def image_dhash(path: str) -> int | None:
    gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return None
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


class AssetFormatter:
    def __init__(self, settings: PipelineSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.config = load_editorial_config(self.settings)
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
        # Motor audiovisual (motion/). Si no esta disponible o falla, se usa el
        # formateador legado de esta clase (fallback automatico por pieza).
        self.motion = MotionEngine(self.settings)

    def close(self) -> None:
        """Libera el worker de render (llamar al terminar la etapa de formato)."""
        self.motion.close()

    def format_row(self, row: Dict[str, object], *, dry_run: bool = False) -> FormattedPackage:
        """Video real -> reel con el video (sus primeros 90 s como mucho); sin video -> imagen o carrusel estatico.

        Nunca se arma un reel animando fotos. El video ya llega descargado,
        verificado y (si correspondia) recortado por la etapa de multimedia del
        pipeline (``media_json.video``).
        """
        editorial = self._load_json(row.get("editorial_json"))
        assets = self._load_assets(row.get("assets_json"))
        raw_payload = self._load_json(row.get("raw_payload_json"))
        media = self._load_json(row.get("media_json"))
        video = media.get("video") if isinstance(media.get("video"), dict) else None
        content_key = str(row.get("content_key") or "")
        caption = str(editorial.get("caption") or "").strip()
        if dry_run:
            package = self._format_dry_run(content_key, row=row, assets=assets, editorial=editorial, caption=caption, video=video)
            self._validate_package(package, dry_run=True)
            return package
        if video and video.get("path"):
            package = self._format_video_piece(content_key, row=row, editorial=editorial, raw_payload=raw_payload, caption=caption, video=video)
        else:
            minimum = self.config.image_min_score(row.get("source"))
            image_ok = minimum is not None and float(row.get("relevance_score") or 0) >= minimum
            if (self.config.requires_video(row.get("source")) and not image_ok) or str(row.get("source_type") or "").lower() == "x_video":
                raise RuntimeError(f"{content_key} exige video real y no tiene uno verificado")
            package = self._format_static(content_key, row=row, assets=assets, editorial=editorial, raw_payload=raw_payload, caption=caption)
        self._validate_package(package, dry_run=False)
        return package

    # ------------------------------------------------------------------
    # Video real: un reel con el video (primeros 90 s como mucho) + portada
    # ------------------------------------------------------------------

    def _format_video_piece(
        self,
        content_key: str,
        *,
        row: Dict[str, object],
        editorial: Dict[str, object],
        raw_payload: Dict[str, object],
        caption: str,
        video: Dict[str, object],
    ) -> FormattedPackage:
        source = str(video.get("path") or "")
        duration = float(video.get("duration_seconds") or 0.0)
        if duration <= 0:
            raise RuntimeError(f"{content_key} video sin duracion valida")
        if duration > self.config.max_reel_seconds + 0.5:
            raise RuntimeError(f"{content_key} video de {duration:.0f}s supera el tope de {self.config.max_reel_seconds:.0f}s")
        seconds = min(duration, self.config.max_reel_seconds)
        started = time.monotonic()
        path, style, brief = self._render_video_segment(
            content_key,
            row=row,
            editorial=editorial,
            raw_payload=raw_payload,
            segment=source,
            seconds=seconds,
            output=self.settings.formatted_video_dir / f"{content_key}_reel.mp4",
        )
        cover = self._render_cover(content_key, row=row, brief=brief, source_video=source, rendered_video=path)
        return FormattedPackage(
            content_key=content_key,
            post_type="reel",
            caption=caption,
            thumbnail_path=cover,
            assets=[Asset(kind="video", path=path, duration_seconds=seconds, meta={"role": "publish"})],
            meta={
                "overlay": editorial.get("overlay"),
                "source_media_type": row.get("media_type"),
                "style": style,
                "video_source_kind": video.get("kind"),
                "video_source_duration": duration,
                # Portada 9:16 con lo importante dentro del recorte 4:5 del feed (IG cover_url, FB thumbnail).
                "cover_path": cover,
                "render_seconds": round(time.monotonic() - started, 1),
            },
        )

    def _render_cover(self, content_key: str, *, row: Dict[str, object], brief: object, source_video: str, rendered_video: str) -> str:
        """Portada del motor (cuadro del video + titular); si el motor no responde, un cuadro del reel."""
        out = self.settings.formatted_video_dir / f"{content_key}_cover.jpg"
        if brief is not None and self.motion.enabled:
            frame = self._extract_frame(source_video, self.temp_dir / f"{content_key}_frame.jpg")
            try:
                content = self.motion.build_content(content_key, row, brief, photos=[frame] if frame else [])
                return str(self.motion.render_cover(content_key, content, out)["path"])
            except (MotionUnavailable, MotionRenderError) as exc:
                LOGGER.warning("portada_fallback %s: %s", content_key, exc)
        return self._render_thumbnail(rendered_video, out)

    @staticmethod
    def _extract_frame(video_path: str, output: Path) -> str:
        """Cuadro representativo del video original (al 20 %, nunca el negro inicial)."""
        capture = cv2.VideoCapture(video_path)
        frames = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        fps = capture.get(cv2.CAP_PROP_FPS) or 30
        position = min(max(1.5, (frames / fps) * 0.2 if frames else 1.5), 12.0)
        capture.set(cv2.CAP_PROP_POS_MSEC, position * 1000)
        ok, frame = capture.read()
        capture.release()
        if not ok or frame is None:
            return ""
        output.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(output), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        return str(output)

    def _render_video_segment(
        self,
        content_key: str,
        *,
        row: Dict[str, object],
        editorial: Dict[str, object],
        raw_payload: Dict[str, object],
        segment: str,
        seconds: float,
        output: Path,
    ) -> tuple[str, str, object]:
        """Plantilla de video del motor (motion/, "video"); si no responde, el formateador legado."""
        brief = None
        if self.motion.enabled:
            try:
                title_text = self._title_for_visual(editorial, row, raw_payload)
                theme = self._visual_theme_for_row(row, raw_payload=raw_payload, title_text=title_text)
                brief = extract_visual(editorial, row, raw_payload, fallback_title=title_text, theme=theme)
                content = self.motion.build_content(content_key, row, brief, video=segment)
                rendered = self.motion.render_reel(content_key, content, "video", output, seconds=seconds)
                return str(rendered["path"]), "motion_engine:video", brief
            except (MotionUnavailable, MotionRenderError) as exc:
                LOGGER.warning("motion_fallback %s: %s", content_key, exc)
        layout_template = self.video_template_path if self.video_use_layout and self._exists(self.video_template_path) else None
        final_path = process_video_for_instagram(
            segment,
            str(output),
            template_path=layout_template,
            enable_subtitles=self.video_subtitles,
            quality=self.video_quality,
            title_text=str(editorial.get("overlay") or editorial.get("hook") or "").strip() or None,
            output_mode="reel",
        )
        return str(final_path), "legacy_video_formatter", brief

    # ------------------------------------------------------------------
    # Sin video: imagen o carrusel estatico (formato periodistico existente)
    # ------------------------------------------------------------------

    def _format_static(
        self,
        content_key: str,
        *,
        row: Dict[str, object],
        assets: List[Asset],
        editorial: Dict[str, object],
        raw_payload: Dict[str, object],
        caption: str,
    ) -> FormattedPackage:
        if self.motion.enabled:
            started = time.monotonic()
            try:
                title_text = self._title_for_visual(editorial, row, raw_payload)
                theme = self._visual_theme_for_row(row, raw_payload=raw_payload, title_text=title_text)
                brief = extract_visual(editorial, row, raw_payload, fallback_title=title_text, theme=theme)
                local_images = self._motion_local_images(content_key, assets, row=row, raw_payload=raw_payload)
                content = self.motion.build_content(content_key, row, brief, photos=local_images)
                rendered = self.motion.render_post(content_key, content, self.settings.formatted_image_dir)
                paths = rendered["paths"]
                return FormattedPackage(
                    content_key=content_key,
                    post_type="carousel" if len(paths) > 1 else "image",
                    caption=caption,
                    thumbnail_path=paths[0],
                    assets=[
                        Asset(kind="image", path=path, meta={"role": "cover" if index == 0 else "carousel"})
                        for index, path in enumerate(paths)
                    ],
                    meta={
                        "overlay": editorial.get("overlay"),
                        "source_media_type": row.get("media_type"),
                        "style": "motion_engine",
                        "template": "static",
                        "category": brief.category,
                        "render_seconds": round(time.monotonic() - started, 1),
                        "motion_piece": rendered["piece"],
                    },
                )
            except (MotionUnavailable, MotionRenderError) as exc:
                LOGGER.warning("motion_fallback %s: %s", content_key, exc)
        return self._format_image(content_key, row=row, assets=assets, editorial=editorial, raw_payload=raw_payload, caption=caption)

    def _motion_local_images(
        self,
        content_key: str,
        assets: List[Asset],
        *,
        row: Dict[str, object],
        raw_payload: Dict[str, object],
    ) -> List[str]:
        local: List[str] = []
        for index, asset in enumerate(a for a in assets if a.kind == "image"):
            try:
                path = self._ensure_local_image(asset, content_key, index, row=row, raw_payload=raw_payload)
            except RuntimeError:
                continue
            # La imagen de relleno del legado no es una foto real: sin foto -> variante tipografica.
            if asset.remote_url and PLACEHOLDER_URL.search(asset.remote_url):
                continue
            if path and "_fallback." not in Path(path).name:
                local.append(path)
            if len(local) >= 10:
                break
        return self._usable_photos(content_key, local, row=row)

    def _usable_photos(self, content_key: str, paths: List[str], *, row: Dict[str, object]) -> List[str]:
        """Sin fotos repetidas (misma imagen en otro formato/tamano) y sin marcas de agua de medios.

        Si todas las fotos de una fuente con politica de descarte tienen marca, la pieza no sale.
        """
        brands = SOURCE_BRANDS.get(str(row.get("source") or "").lower(), [])
        unique: List[str] = []
        hashes: List[int] = []
        marked: List[str] = []
        for path in paths:
            digest = image_dhash(path)
            if digest is not None and any(bin(digest ^ h).count("1") <= DUPLICATE_HAMMING for h in hashes):
                continue
            if any(same_scene(path, kept) for kept in unique):
                continue
            if is_placeholder_image(path):
                LOGGER.info("imagen generica del medio descartada %s: %s", content_key, Path(path).name)
                continue
            if brands:
                verdict = check_image(path, brands)
                if verdict.blocks:
                    marked.append(f"{Path(path).name}:{verdict.reason}:{verdict.score}")
                    continue
            if digest is not None:
                hashes.append(digest)
            unique.append(path)
        if marked:
            LOGGER.info("fotos con marca de agua descartadas %s: %s", content_key, marked)
        if paths and not unique and marked:
            raise WatermarkBlocked(f"marca_de_agua_en_todas_las_fotos:{';'.join(marked)[:200]}")
        if not unique and self.config.image_min_score(row.get("source")) is not None:
            # TN/Infobae sin video: sin una foto real (solo el logo generico) no se publica.
            raise NoRealPhoto("sin_foto_real:solo_imagen_generica_del_medio")
        return unique

    def _format_dry_run(
        self,
        content_key: str,
        *,
        row: Dict[str, object],
        assets: List[Asset],
        editorial: Dict[str, object],
        caption: str,
        video: Dict[str, object] | None = None,
    ) -> FormattedPackage:
        if video:
            post_type = "reel"
            seconds = min(float(video.get("duration_seconds") or 0.0), self.config.max_reel_seconds)
            planned = [Asset(kind="video", path=str(video.get("path") or ""), duration_seconds=seconds or None)]
        else:
            images = [asset for asset in assets if asset.kind == "image"]
            post_type = "carousel" if len(images) > 1 else "image"
            planned = images[:10]
        return FormattedPackage(
            content_key=content_key,
            post_type=post_type,
            caption=caption,
            thumbnail_path=next((asset.path for asset in planned if asset.path), ""),
            assets=planned,
            meta={
                "dry_run": True,
                "overlay": editorial.get("overlay"),
                "source_media_type": row.get("media_type"),
                "style": "dry_run_no_media_processing",
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
        local_images = self._usable_photos(content_key, local_images, row=row)
        if not local_images:
            if image_errors:
                raise RuntimeError("; ".join(image_errors[:3]))
            raise RuntimeError(f"{content_key} no pudo preparar imagen fuente")

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

        # Primero la imagen propia del asset: si se probara antes la og:image de la nota, todas
        # las fotos del carrusel terminarian siendo la misma.
        push(asset.remote_url)
        article_url = str(row.get("canonical_url") or raw_payload.get("url") or "").strip()
        for candidate in self._discover_article_image_candidates(article_url):
            push(candidate)
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
        # 2.5 s: en las piezas del motor el titular ya esta en pantalla.
        capture.set(cv2.CAP_PROP_POS_MSEC, 2500)
        ok, frame = capture.read()
        if not ok or frame is None:
            capture.set(cv2.CAP_PROP_POS_MSEC, 0)
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
        if package.post_type == "image" and not any(asset.kind == "image" for asset in package.assets):
            raise RuntimeError(f"{package.content_key} post de imagen sin imagen final")
        if package.post_type == "carousel" and len(package.assets) < 2:
            raise RuntimeError(f"{package.content_key} carrusel con menos de dos elementos")
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
