"""Prepare Paparazzi articles for Instagram overlay images."""
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from utils.image_processor import (
    normalize_for_instagram_pink_card,
    normalize_for_instagram_carousel_secondary,
    process_image,
)
from utils.instagram_carousel_slices import (
    create_instagram_carousel_from_news,
    build_raw_news_text,
)
from utils.video_processor import (
    process_video_for_instagram,
    download_video_if_needed,
    get_video_duration_seconds,
)

DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = DATA_DIR / "instagram"
TEMP_DIR = DATA_DIR / "ig_tmp"
MEDIA_DIR = BASE_DIR / "media"

IG_CAPTION_LIMIT = int(os.getenv("IG_CAPTION_LIMIT", "2000"))
IG_TARGET_SIZE = tuple(map(int, os.getenv("IG_TARGET_SIZE", "1080,1350").split(",")))

# === CONFIGURACIÓN DE LOGOS (ESTILO INSTAGRAM FORMATTER) ===
IG_WATERMARK_PATH = os.getenv(
    "IG_WATERMARK_PATH",
    str(MEDIA_DIR / "logo.png"),
)
IG_SQUARE_LOGO_PATH = os.getenv(
    "IG_SQUARE_LOGO_PATH",
    str(DATA_DIR / "logo_cuadrado.png"),
)
IG_FOOTER_LOGO_PATH = os.getenv(
    "IG_FOOTER_LOGO_PATH",
    str(DATA_DIR / "www.HolaSalta.com.png"),
)
IG_SLIDE_ICON_PATH = os.getenv(
    "IG_SLIDE_ICON_PATH",
    str(DATA_DIR / "icono_deslizar.png"),
)
IG_OVERLAY_TEMPLATE_PATH = os.getenv(
    "IG_OVERLAY_TEMPLATE_PATH",
    str(MEDIA_DIR / "PlantillaOverlay.png"),
)

# === CONFIGURACIÓN DE TÍTULO (ESTILO INSTAGRAM FORMATTER) ===
def _resolve_path(value: str) -> str:
    if not value:
        return value
    path = Path(value)
    if not path.is_absolute():
        path = (BASE_DIR / path).resolve()
    return str(path)


IG_TITLE_FONT_PATH = _resolve_path(
    os.getenv("IG_TITLE_FONT_PATH", str(MEDIA_DIR / "Montserrat-ExtraBold.ttf"))
)


def _parse_rgb(value, fallback=(255, 255, 255)):
    if not value:
        return fallback
    text = value.strip()
    if text.startswith("#"):
        text = text[1:]
    if "," in text:
        parts = [p.strip() for p in text.split(",")]
        if len(parts) >= 3:
            try:
                return tuple(int(p) for p in parts[:3])
            except ValueError:
                return fallback
    if len(text) == 6:
        try:
            return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
        except ValueError:
            return fallback
    return fallback


def _parse_offset(value, fallback=(3, 3)):
    if not value:
        return fallback
    parts = [p.strip() for p in value.split(",")]
    if len(parts) >= 2:
        try:
            return (int(parts[0]), int(parts[1]))
        except ValueError:
            return fallback
    return fallback


IG_TITLE_COLOR_RAW = os.getenv("IG_TITLE_COLOR", "255,255,255")
IG_TITLE_SHADOW_COLOR_RAW = os.getenv("IG_TITLE_SHADOW_COLOR", "0,0,0")
IG_TITLE_SHADOW_OFFSET_RAW = os.getenv("IG_TITLE_SHADOW_OFFSET", "0,3")

IG_TITLE_COLOR = _parse_rgb(IG_TITLE_COLOR_RAW, fallback=(255, 255, 255))
IG_TITLE_SHADOW_COLOR = _parse_rgb(IG_TITLE_SHADOW_COLOR_RAW, fallback=(0, 0, 0))
IG_TITLE_SHADOW_OFFSET = _parse_offset(IG_TITLE_SHADOW_OFFSET_RAW, fallback=(0, 3))


def _log(message: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


IG_VIDEO_PROCESS = os.getenv("IG_VIDEO_PROCESS", "1") != "0"
IG_VIDEO_TEMPLATE_PATH = os.getenv(
    "IG_VIDEO_TEMPLATE_PATH",
    str(BASE_DIR / "video_app" / "assets" / "templates" / "hola_salta.json"),
)
IG_VIDEO_SUBTITLES = os.getenv("IG_VIDEO_SUBTITLES", "0") == "1"
IG_VIDEO_QUALITY = os.getenv("IG_VIDEO_QUALITY", "normal")
if IG_VIDEO_QUALITY.lower() in ("", "rapido", "borrador"):
    IG_VIDEO_QUALITY = "normal"
IG_VIDEO_RAW_THRESHOLD_SECONDS = int(os.getenv("IG_VIDEO_RAW_THRESHOLD_SECONDS", "150"))
IG_VIDEO_REEL_THRESHOLD_SECONDS = int(os.getenv("IG_VIDEO_REEL_THRESHOLD_SECONDS", "120"))
IG_VIDEO_OUTPUT_DIR = os.getenv("IG_VIDEO_OUTPUT_DIR", str(DATA_DIR / "instagram_videos"))


def _load_latest_news_file():
    # Prefer AI-enriched files when available so captions/emojis are used.
    ai_files = list(DATA_DIR.glob("nuevas_noticias_paparazzi_ai_*.json"))
    if ai_files:
        return max(ai_files, key=lambda p: p.stat().st_mtime)

    files = list(DATA_DIR.glob("nuevas_noticias_paparazzi*.json"))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _build_caption(titulo, parrafos):
    blocks = []
    if titulo:
        blocks.append(titulo.strip())
    for p in parrafos or []:
        if isinstance(p, str) and p.strip():
            blocks.append(p.strip())

    text = ""
    for block in blocks:
        candidate = block if not text else f"{text}\n\n{block}"
        if len(candidate) > IG_CAPTION_LIMIT:
            if not text:
                text = block[:IG_CAPTION_LIMIT].rstrip()
            break
        text = candidate

    if not text:
        text = "Noticia completa en Paparazzi"
    return text


def _collect_images(noticia):
    images = []
    if noticia.get("imagen_optimizada"):
        images.append(noticia["imagen_optimizada"])
    elif noticia.get("imagen"):
        images.append(noticia["imagen"])

    for img in noticia.get("imagenes_secundarias", []):
        if isinstance(img, dict):
            if img.get("optimizada"):
                images.append(img["optimizada"])
            elif img.get("original"):
                images.append(img["original"])
            elif img.get("url"):
                images.append(img["url"])
        elif isinstance(img, str):
            images.append(img)

    if not images and noticia.get("imagenes_url"):
        images.extend(noticia.get("imagenes_url", []))

    # Dedup
    dedup = []
    seen = set()
    for img in images:
        if img and img not in seen:
            seen.add(img)
            dedup.append(img)
    return dedup


def _safe_slug(value: str) -> str:
    safe = re.sub(r"[^\w-]", "_", value or "")
    safe = re.sub(r"_+", "_", safe).strip("_")
    return safe or "noticia"


def _strip_emojis(value: str) -> str:
    if not value:
        return ""
    return re.sub(r"[\U00010000-\U0010ffff]", "", value).strip()


def _clean_caption_text(value: str) -> str:
    text = _strip_emojis(value or "")
    text = re.sub(r"#[\w_]+", "", text)
    text = re.sub(r"\s+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _apply_na_black_box(image_path: str) -> None:
    if not image_path or not os.path.exists(image_path):
        return
    try:
        from PIL import Image, ImageDraw

        with Image.open(image_path) as base:
            if base.mode != "RGBA":
                base = base.convert("RGBA")
            width, height = base.size
            box_w = int(width * 0.42)
            box_h = int(height * 0.18)
            box_x = 0
            box_y = height - box_h
            draw = ImageDraw.Draw(base)
            draw.rectangle([box_x, box_y, box_x + box_w, box_y + box_h], fill=(0, 0, 0))
            base.convert("RGB").save(image_path, quality=95)
    except Exception:
        return


def _prepare_na_source_with_black_box(image_path: str, slug: str) -> str:
    """Create a temp copy of source image and apply NA black box on that copy."""
    if not image_path or not os.path.exists(image_path):
        return image_path
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(image_path).suffix or ".jpg"
    temp_path = TEMP_DIR / f"{slug}_na_box_src{ext}"
    try:
        shutil.copy2(image_path, temp_path)
        _apply_na_black_box(str(temp_path))
        return str(temp_path)
    except Exception:
        return image_path


def _ensure_local(path_or_url, slug, idx):
    if not path_or_url:
        return None
    if str(path_or_url).startswith("http"):
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{slug}_{idx}_src.jpg"
        return process_image(path_or_url, filename, str(TEMP_DIR))
    return path_or_url


def _ensure_local_video(path_or_url, slug, idx):
    if not path_or_url:
        return None
    if str(path_or_url).startswith("http"):
        return download_video_if_needed(path_or_url, slug, idx)
    return path_or_url


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Formatea noticias para Instagram.")
    parser.add_argument("--input", help="Archivo nuevas_noticias_paparazzi*.json (opcional)")
    parser.add_argument("--max", type=int, default=None, help="Maximo de noticias a procesar")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    news_file = Path(args.input) if args.input else _load_latest_news_file()
    if not news_file:
        _log("No news file found in data/")
        return
    if not news_file.exists():
        _log(f"No se encontro el archivo: {news_file}")
        return

    with open(news_file, "r", encoding="utf-8") as f:
        noticias = json.load(f)

    if isinstance(noticias, dict):
        noticias = noticias.get("items") or noticias.get("noticias") or []

    results = []
    _log(f"Usando archivo: {news_file.name}")

    processed = 0
    for noticia in noticias:
        decision = (noticia.get("decision") or "").lower()
        if decision in ("descartar", "descartada", "rechazado", "rechazada"):
            _log("Noticia descartada, se omite.")
            continue

        titulo_base = noticia.get("titulo", "")
        titulo_instagram = noticia.get("titulo_instagram") or titulo_base
        titulo = titulo_instagram or titulo_base
        titulo_overlay = _strip_emojis(titulo)
        slug = _safe_slug(noticia.get("slug") or titulo_base or titulo_instagram)
        slug = slug[:60]

        caption = (noticia.get("texto_instagram") or noticia.get("caption") or "").strip()
        if not caption:
            caption = _build_caption(titulo, noticia.get("parrafos", []))
        caption = _clean_caption_text(caption)
        source = (noticia.get("source") or "").lower()
        if source == "noticiasargentinas":
            # For carousel slide 1, use IG formatter style (layout + title + 4:5).
            primary = None
            image_urls = noticia.get("imagenes_url") or []
            if image_urls:
                primary = _ensure_local(image_urls[0], f"{slug}_na_original", 0)
            if not primary:
                primary = noticia.get("imagen") or noticia.get("imagen_optimizada")
            if not primary:
                _log("Noticias Argentinas: sin imagen principal, se omite.")
                continue

            primary_for_formatter = _prepare_na_source_with_black_box(primary, slug)
            formatted_primary_name = f"{slug}_01_image.jpg"
            formatted_primary = normalize_for_instagram_pink_card(
                primary_for_formatter,
                output_filename=formatted_primary_name,
                folder=str(OUTPUT_DIR),
                target_size=IG_TARGET_SIZE,
                corner_logo_path=IG_SQUARE_LOGO_PATH if os.path.exists(IG_SQUARE_LOGO_PATH) else None,
                slide_icon_path=IG_SLIDE_ICON_PATH if os.path.exists(IG_SLIDE_ICON_PATH) else None,
                center_logo_path=IG_WATERMARK_PATH if os.path.exists(IG_WATERMARK_PATH) else None,
                footer_logo_path=IG_FOOTER_LOGO_PATH if os.path.exists(IG_FOOTER_LOGO_PATH) else None,
                title_text=titulo_overlay,
                title_font_path=IG_TITLE_FONT_PATH if os.path.exists(IG_TITLE_FONT_PATH) else None,
                title_color=IG_TITLE_COLOR,
                title_shadow_color=IG_TITLE_SHADOW_COLOR,
                title_shadow_offset=IG_TITLE_SHADOW_OFFSET,
                overlay_template_path=IG_OVERLAY_TEMPLATE_PATH if os.path.exists(IG_OVERLAY_TEMPLATE_PATH) else None,
            )
            if not formatted_primary or not os.path.exists(formatted_primary):
                _log("Noticias Argentinas: no se pudo generar imagen principal formateada, se omite.")
                continue

            raw_text = build_raw_news_text(noticia)
            try:
                overlay_images = create_instagram_carousel_from_news(
                    formatted_primary,
                    raw_text,
                    str(OUTPUT_DIR),
                    slug,
                )
            except Exception as exc:
                _log(f"[WARN] Carousel texto falló: {exc}")
                overlay_images = []
            if not overlay_images:
                _log("Noticias Argentinas: no se generaron slides, se omite.")
                continue
            images = [primary]
            _log(f"Noticias Argentinas: carousel generado | slides={len(overlay_images)}")
        else:
            images = _collect_images(noticia)
            _log(f"Noticia: {titulo[:80]} | imagenes={len(images)}")

        local_images = []
        if source != "noticiasargentinas":
            for idx, img in enumerate(images):
                local = _ensure_local(img, slug, idx)
                if local:
                    local_images.append(local)

        if source != "noticiasargentinas":
            overlay_images = []
            has_multiple = len(local_images) > 1

            for idx, img_path in enumerate(local_images):
                output_name = f"{slug}_{idx}_ig.jpg"
                output_path = str(OUTPUT_DIR / output_name)
                
                # === LLAMADA SIMPLIFICADA - ESTILO INSTAGRAM FORMATTER ===
                if idx == 0:
                    result = normalize_for_instagram_pink_card(
                        img_path,
                        output_filename=output_name,
                        folder=str(OUTPUT_DIR),
                        target_size=IG_TARGET_SIZE,
                        corner_logo_path=IG_SQUARE_LOGO_PATH if os.path.exists(IG_SQUARE_LOGO_PATH) else None,
                        slide_icon_path=IG_SLIDE_ICON_PATH if has_multiple and os.path.exists(IG_SLIDE_ICON_PATH) else None,
                        center_logo_path=IG_WATERMARK_PATH if os.path.exists(IG_WATERMARK_PATH) else None,
                        footer_logo_path=IG_FOOTER_LOGO_PATH if os.path.exists(IG_FOOTER_LOGO_PATH) else None,
                        title_text=titulo_overlay,
                        title_font_path=IG_TITLE_FONT_PATH if os.path.exists(IG_TITLE_FONT_PATH) else None,
                        title_color=IG_TITLE_COLOR,
                        title_shadow_color=IG_TITLE_SHADOW_COLOR,
                        title_shadow_offset=IG_TITLE_SHADOW_OFFSET,
                        overlay_template_path=IG_OVERLAY_TEMPLATE_PATH if os.path.exists(IG_OVERLAY_TEMPLATE_PATH) else None,
                    )
                else:
                    result = normalize_for_instagram_carousel_secondary(
                        img_path,
                        output_filename=output_name,
                        folder=str(OUTPUT_DIR),
                        target_size=IG_TARGET_SIZE,
                        corner_logo_path=IG_SQUARE_LOGO_PATH if os.path.exists(IG_SQUARE_LOGO_PATH) else None,
                        bottom_logo_path=IG_WATERMARK_PATH if os.path.exists(IG_WATERMARK_PATH) else None,
                        overlay_template_path=IG_OVERLAY_TEMPLATE_PATH if os.path.exists(IG_OVERLAY_TEMPLATE_PATH) else None,
                    )
                if result and os.path.exists(result):
                    overlay_images.append(result)
                elif result:
                    _log(f"[WARN] Imagen generada pero no encontrada: {result}")

        # Videos (process to 9:16 with purple bars + logo)
        processed_videos = []
        reel_videos = []
        video_items = noticia.get("videos_locales") or noticia.get("videos_url") or []
        if IG_VIDEO_PROCESS and video_items:
            _log(f"Videos detectados: {len(video_items)}")
            Path(IG_VIDEO_OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
            has_cover_image = bool(overlay_images)
            for vid_idx, video_src in enumerate(video_items):
                _log(f"Video {vid_idx+1}/{len(video_items)}: {video_src}")
                local_video = _ensure_local_video(video_src, slug, vid_idx)
                if not local_video:
                    _log("  No se pudo descargar/leer el video.")
                    continue
                duration = get_video_duration_seconds(local_video)
                # Solo Reel (no feed)
                reel_name = f"{slug}_video_{vid_idx}_reel.mp4"
                reel_path = str(Path(IG_VIDEO_OUTPUT_DIR) / reel_name)
                try:
                    _log(f"  Reel extra -> {reel_path}")
                    start_reel = time.time()
                    reel_video = process_video_for_instagram(
                        local_video,
                        reel_path,
                        template_path=None,
                        enable_subtitles=IG_VIDEO_SUBTITLES,
                        quality=IG_VIDEO_QUALITY,
                        title_text=None,
                        output_mode="reel",
                    )
                    if reel_video and os.path.exists(reel_video):
                        _log(f"  Reel OK ({time.time() - start_reel:.1f}s)")
                        reel_videos.append(reel_video)
                    elif reel_video:
                        _log(f"  [WARN] Reel generado pero no encontrado: {reel_video}")
                    else:
                        _log("  Reel fallo al procesar.")
                except Exception as exc:
                    _log(f"[WARN] Reel processing error: {exc}")

        key_seed = f"{noticia.get('url','')}|{titulo}"
        ig_key = hashlib.sha1(key_seed.encode("utf-8")).hexdigest()

        carousel_media = []
        if overlay_images and processed_videos:
            carousel_media.append({"type": "image", "path": overlay_images[0]})
            carousel_media.extend({"type": "video", "path": v} for v in processed_videos)
        elif processed_videos:
            carousel_media.extend({"type": "video", "path": v} for v in processed_videos)

        results.append({
            "titulo": titulo,
            "texto_instagram": caption,
            "imagenes_locales": overlay_images,
            "videos_url": noticia.get("videos_url", []),
            "videos_locales": processed_videos,
            "carousel_media": carousel_media,
            "reels": reel_videos,
            "source_url": noticia.get("url"),
            "decision": noticia.get("decision"),
            "decision_reason": noticia.get("decision_reason"),
            "dedup_status": noticia.get("dedup_status"),
            "dedup_score": noticia.get("dedup_score"),
            "ig_key": ig_key,
        })
        processed += 1
        if args.max and processed >= args.max:
            break

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    out_file = DATA_DIR / f"noticias_instagram_{timestamp}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    _log(f"Instagram file created: {out_file}")


if __name__ == "__main__":
    main()
