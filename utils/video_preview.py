"""Generate a preview image from a video (processed or raw)."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from utils.video_processor import (
    FFMPEG_BIN,
    download_video_if_needed,
    process_video_for_instagram,
)
DATA_DIR = BASE_DIR / "data"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def _extract_frame(video_path: str, output_path: str, time_sec: float) -> None:
    cmd = [
        FFMPEG_BIN,
        "-y",
        "-ss",
        str(time_sec),
        "-i",
        video_path,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        output_path,
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg failed")


def main() -> None:
    _load_dotenv(BASE_DIR / ".env")
    parser = argparse.ArgumentParser(description="Genera una imagen preview del video.")
    parser.add_argument("input", help="Ruta o URL del video")
    parser.add_argument("--time", type=float, default=1.0, help="Segundo a capturar")
    parser.add_argument("--output", help="Ruta de salida .jpg")
    parser.add_argument("--processed", action="store_true", help="El video ya esta procesado")
    parser.add_argument("--title", help="Titulo para el primer frame (solo si se procesa)")
    parser.add_argument("--mode", choices=["reel", "feed"], help="Modo de salida (reel/feed)")
    parser.add_argument("--open", action="store_true", help="Abrir la imagen al finalizar")
    args = parser.parse_args()

    template_path = os.getenv(
        "IG_VIDEO_TEMPLATE_PATH",
        str(BASE_DIR / "video_app" / "assets" / "templates" / "hola_salta.json"),
    )
    enable_subtitles = os.getenv("IG_VIDEO_SUBTITLES", "0") == "1"
    quality = os.getenv("IG_VIDEO_QUALITY", "rapido")
    output_mode = args.mode or os.getenv("IG_VIDEO_OUTPUT_MODE", "reel")

    local_video = download_video_if_needed(args.input, "preview", 0)
    if not local_video:
        raise RuntimeError("No se pudo descargar/leer el video.")

    preview_dir = DATA_DIR / "video_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)

    processed_path = local_video
    if not args.processed:
        processed_dir = DATA_DIR / "instagram_videos_previews"
        processed_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(local_video).stem
        processed_path = str(processed_dir / f"{stem}_processed.mp4")
        processed = process_video_for_instagram(
            local_video,
            processed_path,
            template_path=template_path if os.path.exists(template_path) else None,
            enable_subtitles=enable_subtitles,
            quality=quality,
            title_text=args.title,
            output_mode=output_mode,
        )
        if not processed:
            raise RuntimeError("No se pudo procesar el video.")
        processed_path = processed

    if args.output:
        output_path = args.output
    else:
        output_path = str(preview_dir / f"{Path(processed_path).stem}_preview.jpg")

    _extract_frame(processed_path, output_path, args.time)
    print(f"Preview creada: {output_path}")

    if args.open:
        try:
            os.startfile(output_path)
        except Exception:
            pass


if __name__ == "__main__":
    main()
