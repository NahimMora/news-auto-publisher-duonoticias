"""Fast layout preview using FFmpeg (no frame-by-frame)."""
import argparse
import os
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")


def _latest_image():
    candidates = []
    for folder in (DATA_DIR / "fotos", DATA_DIR / "instagram", DATA_DIR):
        if not folder.exists():
            continue
        candidates.extend(folder.glob("*.jpg"))
        candidates.extend(folder.glob("*.jpeg"))
        candidates.extend(folder.glob("*.png"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _run_ffmpeg(cmd: list) -> None:
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg fallo")


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview rapido del layout de video usando una imagen.")
    parser.add_argument("--input", help="Ruta de imagen (jpg/png). Si no se indica, toma la mas reciente.")
    parser.add_argument("--title", help="Titulo para el preview")
    parser.add_argument("--output", help="Ruta de salida .jpg")
    parser.add_argument("--open", action="store_true", help="Abrir la imagen al finalizar")
    args = parser.parse_args()

    template_path = os.getenv(
        "IG_VIDEO_TEMPLATE_PATH",
        str(BASE_DIR / "video_app" / "assets" / "templates" / "hola_salta.json"),
    )
    overlay_path = None
    if os.path.exists(template_path):
        try:
            import json
            data = json.loads(Path(template_path).read_text(encoding="utf-8"))
            overlay_path = data.get("background_image")
        except Exception:
            overlay_path = None
    if overlay_path and not os.path.exists(overlay_path):
        overlay_path = None

    image_path = args.input or _latest_image()
    if not image_path:
        raise RuntimeError("No se encontro imagen para preview.")

    output_mode = os.getenv("IG_VIDEO_OUTPUT_MODE", "reel").lower()
    if output_mode == "feed":
        target_w, target_h = 1080, 1350
        content_h = target_h
    else:
        target_w, target_h = 1080, 1920
        content_h = int(target_w * 5 / 4)
    blur_sigma = float(os.getenv("IG_VIDEO_BLUR_SIGMA", "28"))

    filter_parts = [
        f"[0:v]scale={target_w}:{content_h},gblur=sigma={blur_sigma}[bg]",
        f"[0:v]scale={target_w}:{content_h}:force_original_aspect_ratio=decrease,pad={target_w}:{content_h}:(ow-iw)/2:(oh-ih)/2:color=black@0[fg]",
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[content]",
    ]
    last = "content"
    inputs = 1
    if overlay_path:
        filter_parts.append(f"[{inputs}:v]scale={target_w}:{target_h}[bgimg]")
        filter_parts.append(f"[bgimg][{last}]overlay=(W-w)/2:(H-h)/2[base]")
        last = "base"
        inputs += 1
    else:
        if content_h != target_h:
            filter_parts.append(f"[0:v]scale={target_w}:{target_h},gblur=sigma={blur_sigma}[bg_full]")
            filter_parts.append(f"[bg_full][{last}]overlay=(W-w)/2:(H-h)/2[base]")
            last = "base"
        else:
            filter_parts.append(f"[{last}]null[base]")
            last = "base"
    filter_parts.append(f"[{last}]null[vout]")
    filtergraph = ";".join(filter_parts)

    preview_dir = DATA_DIR / "video_layout_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output or str(preview_dir / "layout_preview.jpg")

    cmd = [FFMPEG_BIN, "-y", "-loop", "1", "-i", str(image_path)]
    if overlay_path:
        cmd += ["-i", overlay_path]
    cmd += [
        "-filter_complex",
        filtergraph,
        "-map",
        "[vout]",
        "-frames:v",
        "1",
        output_path,
    ]

    _run_ffmpeg(cmd)
    print(f"Preview creada: {output_path}")

    if args.open:
        try:
            os.startfile(output_path)
        except Exception:
            pass


if __name__ == "__main__":
    main()
