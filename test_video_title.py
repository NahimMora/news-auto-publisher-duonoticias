"""Test video title overlay with real video and real title."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils.video_processor import process_video_for_instagram

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
VIDEOS_DIR = DATA_DIR / "videos"
OUTPUT_DIR = DATA_DIR / "test_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TEMPLATE_PATH = str(BASE_DIR / "video_app" / "assets" / "templates" / "hola_salta.json")


def find_test_video():
    for folder in [VIDEOS_DIR, DATA_DIR, DATA_DIR / "instagram_videos"]:
        if folder.exists():
            for f in sorted(folder.glob("*.mp4")):
                return str(f)
    return None


def find_real_title():
    files = list(DATA_DIR.glob("noticias_instagram_*.json"))
    if not files:
        return None, None
    latest = max(files, key=lambda p: p.stat().st_mtime)
    data = json.loads(latest.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("items") or data.get("noticias") or []
    if not data:
        return None, latest
    title = (data[0].get("titulo") or data[0].get("title") or "").strip()
    return title or None, latest


def extract_preview_image(video_path: str, image_path: str, time_sec: float = 1.0):
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(time_sec),
        "-i",
        video_path,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        image_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def main():
    test_video = find_test_video()
    if not test_video:
        print("[ERROR] No se encontro ningun video .mp4 para testear")
        return

    real_title, news_file = find_real_title()
    if not real_title:
        print("[ERROR] No se encontro un titulo real en noticias_instagram_*.json")
        return

    output_path = str(OUTPUT_DIR / "preview_real_borrador.mp4")
    output_image = str(OUTPUT_DIR / "preview_real_borrador.png")

    print("=" * 60)
    print("TEST: Video real + titulo real (borrador)")
    print("=" * 60)
    print(f"Input:    {test_video}")
    print(f"Template: {TEMPLATE_PATH}")
    print(f"Output:   {output_path}")
    print(f"Noticias: {news_file.name if news_file else 'N/A'}")
    print(f"Titulo ({len(real_title)} chars):")
    print(f"  {real_title[:80]}...")
    print("=" * 60)
    print()

    try:
        result = process_video_for_instagram(
            test_video,
            output_path,
            template_path=TEMPLATE_PATH,
            enable_subtitles=False,
            quality="borrador",
            title_text=real_title,
            output_mode="reel",
        )
        extract_preview_image(result, output_image, time_sec=1.0)
        print()
        print("=" * 60)
        print(f"[OK] Video generado: {result}")
        print(f"[OK] Imagen preview: {output_image}")
        print("[OK] Revisa el video para verificar:")
        print("     - El video no esta deformado (1080x1920)")
        print("     - El overlay se aplica correctamente")
        print("     - El titulo esta centrado y no se desborda")
        print("     - El word-wrap funciona correctamente")
        print("=" * 60)
    except Exception as exc:
        print(f"[ERROR] Fallo: {exc}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
