"""Render legacy vs premium Instagram image layout previews."""
from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from utils.image_processor import (
    normalize_for_instagram_carousel_secondary,
    normalize_for_instagram_pink_card,
    normalize_for_instagram_premium_card,
    normalize_for_instagram_premium_secondary,
    normalize_for_instagram_premium_v2_card,
    normalize_for_instagram_premium_v2_secondary,
)

DATA_DIR = ROOT_DIR / "data"
MEDIA_DIR = ROOT_DIR / "media"


def _safe_slug(value: str) -> str:
    safe = re.sub(r"[^\w-]", "_", value or "")
    safe = re.sub(r"_+", "_", safe).strip("_")
    return safe[:70] or "preview"


def _title_from_path(path: Path) -> str:
    text = path.stem
    text = re.sub(r"_[0-9]+_(source|src|original|optimized)$", "", text)
    text = re.sub(r"_(source|src|original|optimized|img[0-9]+)$", "", text)
    text = text.replace("_", " ").strip()
    return re.sub(r"\s+", " ", text).title() or "Noticia"


def _category_for_title(title: str) -> tuple[str, str]:
    text = title.lower()
    groups = (
        ("sensitive", "INFORMACION", ("muerte", "muerto", "asesin", "abuso", "violencia", "preso", "carcel", "crimen")),
        ("politics", "POLITICA", ("milei", "gobierno", "congreso", "senado", "diputado", "ministro", "nacion")),
        ("business", "ECONOMIA", ("dolar", "mercado", "economia", "banco", "inflacion", "financiero")),
        ("sports", "DEPORTES", ("boca", "river", "seleccion", "torneo", "futbol", "partido", "racing")),
        ("showbiz", "ESPECTACULOS", ("telefe", "actriz", "actor", "cantante", "romance", "famos", "wanda", "lali", "sofia")),
    )
    for theme, label, keywords in groups:
        if any(keyword in text for keyword in keywords):
            return theme, label
    return "default", "TENDENCIA"


def _parse_target_size(value: str) -> tuple[int, int]:
    try:
        width, height = [int(part.strip()) for part in value.split(",", 1)]
        return width, height
    except Exception:
        return 1080, 1350


def _resolve_path(value: str) -> str:
    if not value:
        return ""
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str((ROOT_DIR / path).resolve())


def _existing(path: str) -> str | None:
    return path if path and Path(path).exists() else None


def _discover_images(limit: int) -> list[Path]:
    roots = [DATA_DIR / "fotos", DATA_DIR / "ig_tmp", DATA_DIR / "instagram_test"]
    suffixes = {".jpg", ".jpeg", ".png", ".webp"}
    selected: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        candidates: list[Path] = []
        for pattern in ("*_original.*", "*_source.*", "*.jpg", "*.jpeg", "*.png", "*.webp"):
            for path in root.glob(pattern):
                if path in seen or path.suffix.lower() not in suffixes:
                    continue
                seen.add(path)
                candidates.append(path)
        candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        selected.extend(candidates)
        if len(selected) >= limit:
            break
    return selected[:limit]


def _copy_source(path: Path, output_dir: Path, index: int) -> Path:
    source_stem = re.sub(r"_(source|src)$", "", path.stem)
    target = output_dir / f"{index:02d}_{_safe_slug(source_stem)}_source{path.suffix.lower()}"
    shutil.copy2(path, target)
    return target


def _render_sample(
    *,
    source_path: Path,
    output_dir: Path,
    index: int,
    title: str,
    mode: str,
    target_size: tuple[int, int],
) -> dict[str, str]:
    overlay_template = _existing(_resolve_path(os.getenv("IG_OVERLAY_TEMPLATE_PATH", str(MEDIA_DIR / "PlantillaOverlay.png"))))
    title_font = _existing(_resolve_path(os.getenv("IG_TITLE_FONT_PATH", str(MEDIA_DIR / "Montserrat-ExtraBold.ttf"))))
    logo = _existing(_resolve_path(os.getenv("IG_WATERMARK_PATH", str(MEDIA_DIR / "logo.png"))))
    square_logo = _existing(_resolve_path(os.getenv("IG_SQUARE_LOGO_PATH", str(DATA_DIR / "logo_cuadrado.png"))))
    footer_logo = _existing(_resolve_path(os.getenv("IG_FOOTER_LOGO_PATH", str(DATA_DIR / "www.HolaSalta.com.png"))))
    slide_icon = _existing(_resolve_path(os.getenv("IG_SLIDE_ICON_PATH", str(DATA_DIR / "icono_deslizar.png"))))

    slug = f"{index:02d}_{_safe_slug(title)}"
    source_copy = _copy_source(source_path, output_dir, index)
    preview_theme, preview_category = _category_for_title(title)
    result: dict[str, str] = {
        "title": title,
        "source": source_copy.name,
    }

    if mode in {"cover", "all"}:
        legacy_cover = normalize_for_instagram_pink_card(
            str(source_path),
            output_filename=f"{slug}_legacy_cover.jpg",
            folder=str(output_dir),
            target_size=target_size,
            corner_logo_path=square_logo,
            slide_icon_path=slide_icon,
            center_logo_path=logo,
            footer_logo_path=footer_logo,
            title_text=title,
            title_font_path=title_font,
            overlay_template_path=overlay_template,
        )
        premium_cover = normalize_for_instagram_premium_card(
            str(source_path),
            output_filename=f"{slug}_premium_cover.jpg",
            folder=str(output_dir),
            target_size=target_size,
            title_text=title,
            title_font_path=title_font,
            overlay_template_path=overlay_template,
        )
        premium_v2_cover = normalize_for_instagram_premium_v2_card(
            str(source_path),
            output_filename=f"{slug}_premium_v2_cover.jpg",
            folder=str(output_dir),
            target_size=target_size,
            title_text=title,
            kicker_text=preview_category,
            content_theme=preview_theme,
            title_font_path=title_font,
            overlay_template_path=overlay_template,
        )
        if legacy_cover:
            result["legacy_cover"] = Path(legacy_cover).name
        if premium_cover:
            result["premium_cover"] = Path(premium_cover).name
        if premium_v2_cover:
            result["premium_v2_cover"] = Path(premium_v2_cover).name

    if mode in {"secondary", "all"}:
        legacy_secondary = normalize_for_instagram_carousel_secondary(
            str(source_path),
            output_filename=f"{slug}_legacy_secondary.jpg",
            folder=str(output_dir),
            target_size=target_size,
            corner_logo_path=square_logo,
            bottom_logo_path=logo,
            overlay_template_path=overlay_template,
        )
        premium_secondary = normalize_for_instagram_premium_secondary(
            str(source_path),
            output_filename=f"{slug}_premium_secondary.jpg",
            folder=str(output_dir),
            target_size=target_size,
            overlay_template_path=overlay_template,
        )
        premium_v2_secondary = normalize_for_instagram_premium_v2_secondary(
            str(source_path),
            output_filename=f"{slug}_premium_v2_secondary.jpg",
            folder=str(output_dir),
            target_size=target_size,
            content_theme=preview_theme,
            title_font_path=title_font,
            overlay_template_path=overlay_template,
        )
        if legacy_secondary:
            result["legacy_secondary"] = Path(legacy_secondary).name
        if premium_secondary:
            result["premium_secondary"] = Path(premium_secondary).name
        if premium_v2_secondary:
            result["premium_v2_secondary"] = Path(premium_v2_secondary).name

    return result


def _image_cell(row: dict[str, str], key: str, label: str) -> str:
    filename = row.get(key, "")
    if not filename:
        return "<div class=\"empty\">No render</div>"
    safe_file = html.escape(filename)
    return (
        "<figure>"
        f"<img src=\"{safe_file}\" alt=\"{html.escape(label)}\">"
        f"<figcaption>{html.escape(label)}</figcaption>"
        "</figure>"
    )


def _write_gallery(output_dir: Path, rows: Iterable[dict[str, str]], mode: str) -> Path:
    cards = []
    for row in rows:
        cells = [
            _image_cell(row, "source", "Fuente"),
        ]
        if mode in {"cover", "all"}:
            cells.extend(
                [
                    _image_cell(row, "legacy_cover", "Actual portada"),
                    _image_cell(row, "premium_cover", "Premium v1 portada"),
                    _image_cell(row, "premium_v2_cover", "Premium v2 portada"),
                ]
            )
        if mode in {"secondary", "all"}:
            cells.extend(
                [
                    _image_cell(row, "legacy_secondary", "Actual carrusel"),
                    _image_cell(row, "premium_secondary", "Premium v1 carrusel"),
                    _image_cell(row, "premium_v2_secondary", "Premium v2 carrusel"),
                ]
            )
        cards.append(
            "<section class=\"sample\">"
            f"<h2>{html.escape(row.get('title', 'Sin titulo'))}</h2>"
            f"<div class=\"grid\">{''.join(cells)}</div>"
            "</section>"
        )

    document = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Duo Instagram Layout Preview</title>
  <style>
    :root {{ color-scheme: dark; font-family: Arial, sans-serif; background: #111016; color: #f5f2eb; }}
    body {{ margin: 0; padding: 28px; }}
    header {{ margin-bottom: 28px; }}
    h1 {{ margin: 0 0 8px; font-size: 28px; }}
    p {{ margin: 0; color: #b9b3c7; }}
    .sample {{ margin: 0 0 36px; padding-top: 24px; border-top: 1px solid #343040; }}
    h2 {{ margin: 0 0 18px; font-size: 20px; line-height: 1.25; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 18px; align-items: start; }}
    figure {{ margin: 0; background: #191722; border: 1px solid #302b3e; padding: 10px; }}
    img {{ display: block; width: 100%; height: auto; background: #050507; }}
    figcaption {{ margin-top: 9px; color: #d8cf95; font-size: 13px; }}
    .empty {{ min-height: 260px; display: grid; place-items: center; border: 1px dashed #4a4358; color: #9e96ad; }}
  </style>
</head>
<body>
  <header>
    <h1>Duo Instagram Layout Preview</h1>
    <p>Comparacion local entre layout actual, premium v1 y premium v2. No publica ni modifica la cola.</p>
  </header>
  {''.join(cards)}
</body>
</html>
"""
    output_path = output_dir / "index.html"
    output_path.write_text(document, encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a local HTML gallery comparing Instagram image layouts.")
    parser.add_argument("--image", action="append", default=[], help="Source image path. Can be passed multiple times.")
    parser.add_argument("--title", default="", help="Title to use when a single image is provided.")
    parser.add_argument("--limit", type=int, default=6, help="Number of auto-discovered source images.")
    parser.add_argument("--mode", choices=("cover", "secondary", "all"), default="all")
    parser.add_argument("--output-dir", default="", help="Output directory for the preview gallery.")
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) if args.output_dir else DATA_DIR / "layout_previews" / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    sources = [Path(item) for item in args.image if item]
    if not sources:
        sources = _discover_images(max(1, args.limit))
    if not sources:
        raise RuntimeError("No source images found. Pass --image or add images to data/fotos.")

    target_size = _parse_target_size(os.getenv("IG_TARGET_SIZE", "1080,1350"))
    rows = []
    for index, source_path in enumerate(sources, start=1):
        if not source_path.exists():
            continue
        title = args.title if args.title and len(sources) == 1 else _title_from_path(source_path)
        rows.append(
            _render_sample(
                source_path=source_path,
                output_dir=output_dir,
                index=index,
                title=title,
                mode=args.mode,
                target_size=target_size,
            )
        )

    gallery_path = _write_gallery(output_dir, rows, args.mode)
    print(f"Preview gallery: {gallery_path}")


if __name__ == "__main__":
    main()
