"""Health checks for long-running automation."""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data" / "healthcheck"
DATA_DIR.mkdir(parents=True, exist_ok=True)

FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE_BIN = os.getenv("FFMPEG_PROBE_BIN", "ffprobe")

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from utils.image_processor import normalize_for_instagram_news_card
from utils.video_processor import process_video_for_instagram


def _run(cmd: list) -> None:
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Command failed")


def check_dependencies() -> None:
    print("Chequeando dependencias...")
    _run([FFMPEG_BIN, "-version"])
    _run([FFPROBE_BIN, "-version"])
    print("OK dependencias")


def test_imagemagick() -> None:
    print("Test Image -> news card...")
    from PIL import Image, ImageDraw

    src = DATA_DIR / "sample_src.jpg"
    out = DATA_DIR / "sample_card.jpg"
    img = Image.new("RGB", (1200, 800), (20, 20, 20))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 1200, 400], fill=(40, 40, 40))
    img.save(src, format="JPEG", quality=90)

    result = normalize_for_instagram_news_card(
        str(src),
        output_filename=out.name,
        folder=str(DATA_DIR),
        title_text="Salud de prueba",
        title_font_path=os.getenv("IG_TITLE_FONT_PATH", str(BASE_DIR / "media" / "Montserrat-ExtraBold.ttf")),
    )
    if not result or not Path(result).exists():
        raise RuntimeError("Fallo news card")
    print("OK Image")


def _create_sample_video(path: Path) -> None:
    cmd = [
        FFMPEG_BIN,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=1280x720:rate=30",
        "-t",
        "2",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    _run(cmd)


def test_video_modes() -> None:
    print("Test FFmpeg -> feed + reel...")
    src = DATA_DIR / "sample_video.mp4"
    if not src.exists():
        _create_sample_video(src)

    feed_out = DATA_DIR / "sample_feed.mp4"
    reel_out = DATA_DIR / "sample_reel.mp4"
    process_video_for_instagram(
        str(src),
        str(feed_out),
        template_path=None,
        enable_subtitles=False,
        quality="normal",
        title_text="TEST FEED",
        output_mode="feed",
    )
    process_video_for_instagram(
        str(src),
        str(reel_out),
        template_path=None,
        enable_subtitles=False,
        quality="normal",
        title_text="TEST REEL",
        output_mode="reel",
    )
    if not feed_out.exists() or not reel_out.exists():
        raise RuntimeError("Fallo video test")
    print("OK FFmpeg")


def soak_test(iterations: int, delay: float) -> None:
    print(f"SOAK test: {iterations} iteraciones, delay {delay}s")
    for idx in range(iterations):
        print(f"Iteracion {idx + 1}/{iterations}")
        test_video_modes()
        time.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser(description="Healthcheck del pipeline.")
    parser.add_argument("--deps", action="store_true", help="Chequea binarios (ffmpeg/magick).")
    parser.add_argument("--image", action="store_true", help="Test de ImageMagick + news card.")
    parser.add_argument("--video", action="store_true", help="Test de FFmpeg + modos feed/reel.")
    parser.add_argument("--soak", type=int, default=0, help="Soak test (iteraciones).")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay entre iteraciones soak.")
    args = parser.parse_args()

    if not any([args.deps, args.image, args.video, args.soak]):
        args.deps = args.image = args.video = True

    if args.deps:
        check_dependencies()
    if args.image:
        test_imagemagick()
    if args.video:
        test_video_modes()
    if args.soak:
        soak_test(args.soak, args.delay)


if __name__ == "__main__":
    main()
