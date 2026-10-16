"""Create reels from videos and publish with caption (no images)."""
import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable, List, Optional

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

DATA_DIR = BASE_DIR / "data"

from utils.video_processor import download_video_if_needed, process_video_for_instagram
from utils.x_captioner_openai import format_caption_paragraphs
import utils.instagram_graph_publisher as igpub

IG_VIDEO_TEMPLATE_PATH = os.getenv(
    "IG_VIDEO_TEMPLATE_PATH",
    str(BASE_DIR / "video_app" / "assets" / "templates" / "hola_salta.json"),
)
IG_VIDEO_SUBTITLES = os.getenv("IG_VIDEO_SUBTITLES", "0") == "1"
IG_VIDEO_QUALITY = os.getenv("IG_VIDEO_QUALITY", "normal")


def _clean_caption(text: str) -> str:
    cleaned = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    return format_caption_paragraphs(cleaned)


def _latest_news_file() -> Optional[Path]:
    files = list(DATA_DIR.glob("noticias_instagram_*.json"))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _load_items(path: Path) -> List[dict]:
    with open(path, "r", encoding="utf-8") as f:
        items = json.load(f)
    if isinstance(items, dict):
        items = items.get("items") or items.get("noticias") or []
    return items if isinstance(items, list) else []


def _sanitize(text: str, max_len: int = 80) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("_", "-", ".") else "_" for ch in (text or ""))
    safe = "_".join([p for p in safe.split("_") if p]).strip("_")
    return (safe or "video")[:max_len]


def _iter_video_sources(item: dict) -> Iterable[str]:
    reels = item.get("reels") or []
    if reels:
        for r in reels:
            if isinstance(r, dict):
                src = r.get("path") or r.get("url")
            else:
                src = r
            if src:
                yield src
        return
    videos = item.get("videos_locales") or item.get("videos_url") or []
    for v in videos:
        if v:
            yield v


def _item_allowed(item: dict, only_approved: bool) -> bool:
    if not only_approved:
        return True
    decision = (item.get("decision") or "").lower()
    dedup = (item.get("dedup_status") or "").lower()
    return decision == "publicar" or dedup == "publicar"


def _build_key(item: dict, src: str) -> str:
    base = item.get("ig_key") or item.get("source_url") or item.get("titulo") or "item"
    return f"{base}|{src}|reelonly"


def main() -> None:
    parser = argparse.ArgumentParser(description="Create reels from videos and publish with caption.")
    parser.add_argument("--file", help="Path to noticias_instagram_*.json (optional)")
    parser.add_argument("--max", type=int, default=None, help="Max reels to publish")
    parser.add_argument("--output-dir", default=str(DATA_DIR / "instagram_reels"), help="Output folder for reels")
    parser.add_argument("--only-approved", action="store_true", help="Publicar solo items con decision=publicar")
    parser.add_argument("--no-process", action="store_true", help="No procesar, publicar video raw")
    args = parser.parse_args()

    if not igpub.IG_USER_ID:
        raise RuntimeError("Missing IG_USER_ID")

    data_file = Path(args.file) if args.file else _latest_news_file()
    if not data_file or not data_file.exists():
        print("No noticias_instagram_*.json found in data/")
        return

    items = _load_items(data_file)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    published = igpub._load_published_keys()
    count = 0

    for item in items:
        if not _item_allowed(item, args.only_approved):
            continue

        caption = _clean_caption((item.get("texto_instagram") or item.get("caption") or "").strip())
        if not caption:
            print("Saltado: sin texto_instagram/caption", item.get("titulo") or item.get("slug") or "item")
            continue
        slug = _sanitize(item.get("slug") or item.get("titulo") or "reel")

        for idx, src in enumerate(_iter_video_sources(item)):
            key = _build_key(item, src)
            if key in published:
                print("Saltado: ya publicado", key)
                continue

            local = download_video_if_needed(src, slug, idx)
            if not local:
                print("Saltado: no se pudo descargar", src)
                continue

            upload_src = local
            if not args.no_process:
                out_path = output_dir / f"{slug}_reel_{idx}.mp4"
                processed = process_video_for_instagram(
                    local,
                    str(out_path),
                    template_path=None,
                    enable_subtitles=IG_VIDEO_SUBTITLES,
                    quality=IG_VIDEO_QUALITY,
                    title_text=None,
                    output_mode="reel",
                )
                if processed and os.path.exists(processed):
                    upload_src = processed
                else:
                    print("WARN: fallo procesamiento, publico raw")

            try:
                media_url = igpub._resolve_media_url(upload_src)
            except Exception as exc:
                print(f"[ERROR] Upload fallo: {igpub._sanitize_error(str(exc))}")
                continue
            if not media_url:
                print("Saltado: no se pudo obtener URL publica", upload_src)
                continue

            try:
                container_id = igpub._create_media_container(media_url, "video", caption=caption, force_reel=True)
                igpub._wait_container(container_id)
                post_id = igpub._publish_container(container_id)
                if post_id:
                    print(f"Publicado Reel: {post_id}")
                    published.add(key)
                    igpub._save_published_keys(published)
            except Exception as exc:
                print(f"[ERROR] Reel fallo: {igpub._sanitize_error(str(exc))}")

            count += 1
            if args.max and count >= args.max:
                return


if __name__ == "__main__":
    main()
