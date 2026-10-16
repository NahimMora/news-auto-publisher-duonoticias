"""Test script to preview Instagram overlay layout on sample images."""
import argparse
import os
import re
import sys
from pathlib import Path
from typing import Optional, Tuple

from parsel import Selector

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from utils.image_processor import (
    normalize_for_instagram_pink_card,
    normalize_for_instagram_carousel_secondary,
    process_image,
)


def _safe_slug(value: str) -> str:
    safe = re.sub(r"[^\w-]", "_", value or "")
    safe = re.sub(r"_+", "_", safe).strip("_")
    return safe or "noticia"


def _download_image(url: str, dest_dir: Path, name: str) -> Optional[str]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{_safe_slug(name)}_src.jpg"
    return process_image(url, filename, str(dest_dir))


def _find_from_html(html_text: str) -> Tuple[Optional[str], Optional[str]]:
    sel = Selector(text=html_text or "")
    title_parts = sel.xpath(
        "(//h1[contains(@class,'entry-title') or contains(@class,'title')])[1]//text()"
    ).getall()
    if not title_parts:
        title_parts = sel.xpath("(//h1)[1]//text()").getall()
    title = " ".join([t.strip() for t in title_parts if t and t.strip()]) or None

    img = sel.xpath("//meta[@property='og:image']/@content").get()
    if not img:
        img = sel.xpath(
            "(//div[contains(@class,'entry-content')]//img)[1]/@data-src | "
            "(//div[contains(@class,'entry-content')]//img)[1]/@data-lazy-src | "
            "(//div[contains(@class,'entry-content')]//img)[1]/@src"
        ).get()

    return title, img


def _resolve_image(image_arg: Optional[str], html_path: Optional[str], temp_dir: Path) -> Tuple[Optional[str], Optional[str]]:
    if image_arg:
        if image_arg.startswith("http"):
            return _download_image(image_arg, temp_dir, "image"), None
        return image_arg, None

    if html_path:
        html_text = Path(html_path).read_text(encoding="utf-8", errors="ignore")
        title, img_url = _find_from_html(html_text)
        if img_url:
            return _download_image(img_url, temp_dir, title or "noticia"), title
        return None, title

    return None, None


def main() -> None:
    parser = argparse.ArgumentParser(description="Test Instagram overlay layout.")
    parser.add_argument("--html", help="Path to a saved HTML article (optional).")
    parser.add_argument("--image", help="Local path or URL to a source image.")
    parser.add_argument("--title", help="Override title to render in overlay.")
    parser.add_argument("--output-dir", default=str(ROOT_DIR / "data" / "instagram_test"))
    parser.add_argument("--second-image", help="Optional second image for carousel test (path or URL).")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    temp_dir = ROOT_DIR / "data" / "ig_tmp"
    output_dir.mkdir(parents=True, exist_ok=True)

    image_path, detected_title = _resolve_image(args.image, args.html, temp_dir)
    title = args.title or detected_title or "Noticia"

    if not image_path:
        print("No image found. Provide --image or --html with og:image.")
        return

    ig_target_size = tuple(map(int, os.getenv("IG_TARGET_SIZE", "1080,1350").split(",")))
    ig_watermark_path = os.getenv("IG_WATERMARK_PATH", str(ROOT_DIR / "data" / "logo.png"))
    ig_square_logo_path = os.getenv("IG_SQUARE_LOGO_PATH", str(ROOT_DIR / "data" / "logo_square.png"))
    ig_footer_logo_path = os.getenv("IG_FOOTER_LOGO_PATH", str(ROOT_DIR / "data" / "logo_footer.png"))
    ig_slide_icon_path = os.getenv("IG_SLIDE_ICON_PATH", str(ROOT_DIR / "data" / "icono_deslizar.png"))
    def _resolve_path(value: str) -> str:
        if not value:
            return value
        path = Path(value)
        if not path.is_absolute():
            path = (ROOT_DIR / path).resolve()
        return str(path)

    ig_title_font_path = _resolve_path(os.getenv("IG_TITLE_FONT_PATH", str(ROOT_DIR / "media" / "Montserrat-ExtraBold.ttf")))
    ig_overlay_template_path = _resolve_path(os.getenv("IG_OVERLAY_TEMPLATE_PATH", str(ROOT_DIR / "media" / "PlantillaOverlay.png")))
    ig_watermark_image_path = _resolve_path(os.getenv("IG_WATERMARK_IMAGE_PATH", str(ROOT_DIR / "media" / "logo.png")))
    ig_watermark_opacity = float(os.getenv("IG_WATERMARK_OPACITY", "0.5"))
    ig_watermark_scale = float(os.getenv("IG_WATERMARK_SCALE", "0.75"))
    ig_title_color_raw = os.getenv("IG_TITLE_COLOR", "255,255,255")
    ig_title_stroke_width = int(os.getenv("IG_TITLE_STROKE_WIDTH", "6"))
    ig_title_bold_dilate = int(os.getenv("IG_TITLE_BOLD_DILATE", "6"))
    ig_title_shadow_color_raw = os.getenv("IG_TITLE_SHADOW_COLOR", "0,0,0")
    ig_title_shadow_offset_raw = os.getenv("IG_TITLE_SHADOW_OFFSET", "3,3")

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

    ig_title_color = _parse_rgb(ig_title_color_raw, fallback=(255, 255, 255))
    ig_title_shadow_color = _parse_rgb(ig_title_shadow_color_raw, fallback=(0, 0, 0))
    ig_title_shadow_offset = _parse_offset(ig_title_shadow_offset_raw, fallback=(3, 3))

    cover_name = f"{_safe_slug(title)}_cover_ig.jpg"
    cover_path = normalize_for_instagram_pink_card(
        image_path,
        output_filename=cover_name,
        folder=str(output_dir),
        target_size=ig_target_size,
        corner_logo_path=ig_square_logo_path if os.path.exists(ig_square_logo_path) else None,
        slide_icon_path=ig_slide_icon_path if os.path.exists(ig_slide_icon_path) else None,
        center_logo_path=ig_watermark_path if os.path.exists(ig_watermark_path) else None,
        footer_logo_path=ig_footer_logo_path if os.path.exists(ig_footer_logo_path) else None,
        title_text=title,
        title_font_path=ig_title_font_path if os.path.exists(ig_title_font_path) else None,
        title_color=ig_title_color,
        title_stroke_width=ig_title_stroke_width,
        title_bold_dilate=ig_title_bold_dilate,
        title_shadow_color=ig_title_shadow_color,
        title_shadow_offset=ig_title_shadow_offset,
        overlay_template_path=ig_overlay_template_path if os.path.exists(ig_overlay_template_path) else None,
        watermark_image_path=ig_watermark_image_path if os.path.exists(ig_watermark_image_path) else None,
        watermark_image_opacity=ig_watermark_opacity,
        watermark_image_scale=ig_watermark_scale,
    )

    secondary_image_path = image_path
    if args.second_image:
        if args.second_image.startswith("http"):
            secondary_image_path = _download_image(args.second_image, temp_dir, f"{title}_second")
        else:
            secondary_image_path = args.second_image

    secondary_name = f"{_safe_slug(title)}_secondary_ig.jpg"
    secondary_path = normalize_for_instagram_carousel_secondary(
        secondary_image_path,
        output_filename=secondary_name,
        folder=str(output_dir),
        target_size=ig_target_size,
        corner_logo_path=ig_square_logo_path if os.path.exists(ig_square_logo_path) else None,
        bottom_logo_path=ig_watermark_path if os.path.exists(ig_watermark_path) else None,
        overlay_template_path=ig_overlay_template_path if os.path.exists(ig_overlay_template_path) else None,
        watermark_image_path=ig_watermark_image_path if os.path.exists(ig_watermark_image_path) else None,
        watermark_image_opacity=ig_watermark_opacity,
        watermark_image_scale=ig_watermark_scale,
    )

    print("OK")
    print(f"Cover:     {cover_path}")
    print(f"Secondary: {secondary_path}")


if __name__ == "__main__":
    main()
