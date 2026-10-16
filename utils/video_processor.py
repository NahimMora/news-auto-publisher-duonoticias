"""FFmpeg-based video processing for Instagram Reels (9:16)."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from utils.http_client import download_to_file
from PIL import Image, ImageDraw, ImageFont

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────
FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE_BIN = os.getenv("FFMPEG_PROBE_BIN", "ffprobe")
IMAGEMAGICK_BIN = os.getenv("IMAGEMAGICK_BIN", "magick")
FFMPEG_VCODEC = os.getenv("FFMPEG_VCODEC", "libx264")

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"

# Video output dimensions (Instagram Reels = 9:16)
REEL_WIDTH = 1080
REEL_HEIGHT = 1920

# Title configuration defaults
DEFAULT_TITLE_FONT_SIZE = int(os.getenv("IG_VIDEO_TITLE_FONT_SIZE", "72"))
DEFAULT_TITLE_BOTTOM_MARGIN = int(os.getenv("IG_VIDEO_TITLE_BOTTOM_MARGIN", "340"))
DEFAULT_TITLE_PADDING_X = int(os.getenv("IG_VIDEO_TITLE_PADDING_X", "60"))
DEFAULT_TITLE_PADDING_Y = 30
DEFAULT_MAX_WIDTH_RATIO = float(os.getenv("IG_VIDEO_TITLE_MAX_WIDTH_RATIO", "0.80"))
DEFAULT_MAX_LINES = 4

# Video processing
VIDEO_BLUR_SIGMA = float(os.getenv("IG_VIDEO_BLUR_SIGMA", "40"))
VIDEO_PROGRESS = os.getenv("IG_VIDEO_PROGRESS", "1") != "0"

# Quality presets
QUALITY_PRESETS = {
    "borrador": {"crf": 32, "preset": "ultrafast"},
    "rapido": {"crf": 26, "preset": "veryfast"},
    "normal": {"crf": 22, "preset": "medium"},
}


def _resolve_path(value: str) -> Optional[str]:
    """Resolve a relative path to absolute."""
    if not value:
        return None
    path = Path(value)
    if path.is_absolute() and path.exists():
        return str(path)
    for base in [BASE_DIR, BASE_DIR / "video_app", BASE_DIR / "media"]:
        candidate = base / value
        if candidate.exists():
            return str(candidate.resolve())
    return None


def _resolve_font() -> Optional[str]:
    """Find the default title font."""
    font_env = os.getenv("IG_VIDEO_TITLE_FONT_PATH", "")
    if font_env:
        resolved = _resolve_path(font_env)
        if resolved:
            return resolved
    candidates = [
        BASE_DIR / "media" / "Montserrat-ExtraBold.ttf",
        BASE_DIR / "video_app" / "assets" / "fonts" / "Montserrat-ExtraBold.ttf",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


DEFAULT_FONT_PATH = _resolve_font()


# ─────────────────────────────────────────────────────────────────────────────
# ImageMagick text measurement
# ─────────────────────────────────────────────────────────────────────────────
_MAGICK_BIN: Optional[str] = None
_TEXT_WIDTH_CACHE: dict = {}
_LINE_HEIGHT_CACHE: dict = {}
_STROKE_OFFSET_CACHE: dict[int, list[tuple[int, int]]] = {}


def _get_magick_bin() -> Optional[str]:
    global _MAGICK_BIN
    if _MAGICK_BIN is not None:
        return _MAGICK_BIN if _MAGICK_BIN else None
    for candidate in [IMAGEMAGICK_BIN, "magick", "magick.exe"]:
        if candidate and shutil.which(candidate):
            _MAGICK_BIN = candidate
            return candidate
    _MAGICK_BIN = ""
    return None


def _measure_text_width(text: str, font_path: Optional[str], font_size: int) -> int:
    """Measure text width using ImageMagick or approximation."""
    if not text:
        return 0
    key = (text, font_path, font_size)
    if key in _TEXT_WIDTH_CACHE:
        return _TEXT_WIDTH_CACHE[key]

    magick = _get_magick_bin()
    if magick and font_path and Path(font_path).exists():
        try:
            cmd = [magick, "-font", font_path, "-pointsize", str(font_size),
                   f"label:{text}", "-format", "%w", "info:"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                width = int(result.stdout.strip() or "0")
                _TEXT_WIDTH_CACHE[key] = width
                return width
        except Exception:
            pass

    # Fallback: approximate based on character count
    approx = int(len(text) * font_size * 0.55)
    _TEXT_WIDTH_CACHE[key] = approx
    return approx


def _measure_line_height(font_path: Optional[str], font_size: int) -> int:
    """Measure line height using ImageMagick or approximation."""
    key = (font_path, font_size)
    if key in _LINE_HEIGHT_CACHE:
        return _LINE_HEIGHT_CACHE[key]

    magick = _get_magick_bin()
    if magick and font_path and Path(font_path).exists():
        try:
            cmd = [magick, "-font", font_path, "-pointsize", str(font_size),
                   "label:Ay", "-format", "%h", "info:"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                height = int(result.stdout.strip() or "0")
                if height > 0:
                    _LINE_HEIGHT_CACHE[key] = height
                    return height
        except Exception:
            pass

    approx = int(font_size * 1.25)
    _LINE_HEIGHT_CACHE[key] = approx
    return approx


# ─────────────────────────────────────────────────────────────────────────────
# Text wrapping
# ─────────────────────────────────────────────────────────────────────────────
def _normalize_text(text: str) -> str:
    """Clean and normalize text for display."""
    if not text:
        return ""
    # Remove all newlines and normalize spaces
    result = text.replace("\\r\\n", " ").replace("\\n", " ")
    result = result.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    result = result.replace("\u00a0", " ").replace("\t", " ")
    # Collapse multiple spaces
    while "  " in result:
        result = result.replace("  ", " ")
    return result.strip()


def _wrap_text(
    text: str,
    font_path: Optional[str],
    font_size: int,
    max_width: int,
    max_lines: int = 4,
) -> list[str]:
    """Word-wrap text to fit within max_width, respecting max_lines."""
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    current_line = ""

    for word in words:
        if not current_line:
            test_line = word
        else:
            test_line = f"{current_line} {word}"

        line_width = _measure_text_width(test_line, font_path, font_size)

        if line_width <= max_width:
            current_line = test_line
        else:
            # Current line is full, save it and start new
            if current_line:
                lines.append(current_line)
                if len(lines) >= max_lines:
                    break
            
            # Check if single word fits
            word_width = _measure_text_width(word, font_path, font_size)
            if word_width <= max_width:
                current_line = word
            else:
                # Word too long, must be truncated
                truncated = _truncate_word(word, font_path, font_size, max_width)
                current_line = truncated

    # Add remaining line
    if current_line and len(lines) < max_lines:
        lines.append(current_line)

    return lines


def _load_pil_font(font_path: Optional[str], font_size: int) -> ImageFont.FreeTypeFont:
    """Load a TTF font for PIL, fallback to default if missing."""
    if font_path and Path(font_path).exists():
        try:
            return ImageFont.truetype(font_path, font_size)
        except Exception:
            pass
    return ImageFont.load_default()


def _wrap_text_pil(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        test_line = word if not current else f"{current} {word}"
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            current = test_line
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _measure_text_block(draw: ImageDraw.ImageDraw, lines: list[str], font: ImageFont.FreeTypeFont, line_spacing: int) -> tuple[int, int, int]:
    if not lines:
        return 0, 0, 0
    line_height = font.getbbox("Ag")[3]
    widths = [draw.textbbox((0, 0), line, font=font)[2] for line in lines]
    text_width = max(widths) if widths else 0
    text_height = (line_height * len(lines)) + (line_spacing * max(0, len(lines) - 1))
    return line_height, text_height, text_width


def _coerce_rgb(color: object, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    if isinstance(color, (list, tuple)) and len(color) >= 3:
        try:
            return (int(color[0]), int(color[1]), int(color[2]))
        except (TypeError, ValueError):
            return fallback
    return fallback


def _coerce_rgba(
    color: object,
    fallback: tuple[int, int, int],
    alpha: int = 255,
) -> tuple[int, int, int, int]:
    rgb = _coerce_rgb(color, fallback)
    return rgb[0], rgb[1], rgb[2], int(alpha)


def _coerce_offset(offset: object, fallback: tuple[int, int] = (0, 0)) -> tuple[int, int]:
    if isinstance(offset, (list, tuple)):
        try:
            if len(offset) >= 2:
                return int(offset[0]), int(offset[1])
            if len(offset) == 1:
                value = int(offset[0])
                return value, value
        except (TypeError, ValueError):
            return fallback
    if isinstance(offset, str):
        parts = [part.strip() for part in offset.split(",") if part.strip()]
        try:
            if len(parts) >= 2:
                return int(parts[0]), int(parts[1])
            if len(parts) == 1:
                value = int(parts[0])
                return value, value
        except ValueError:
            return fallback
    try:
        value = int(offset)
    except (TypeError, ValueError):
        return fallback
    return value, value


def _coerce_offset_list(offsets: object) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    if not isinstance(offsets, (list, tuple)):
        return result
    for item in offsets:
        offset = _coerce_offset(item, fallback=(0, 0))
        if offset != (0, 0):
            result.append(offset)
    return result


def _stroke_offsets(stroke_width: int) -> list[tuple[int, int]]:
    if stroke_width <= 0:
        return []
    cached = _STROKE_OFFSET_CACHE.get(stroke_width)
    if cached is not None:
        return cached

    offsets: list[tuple[int, int]] = []
    radius_sq = stroke_width * stroke_width
    for dx in range(-stroke_width, stroke_width + 1):
        for dy in range(-stroke_width, stroke_width + 1):
            if dx == 0 and dy == 0:
                continue
            if (dx * dx) + (dy * dy) <= radius_sq:
                offsets.append((dx, dy))
    _STROKE_OFFSET_CACHE[stroke_width] = offsets
    return offsets


def _draw_text_layer(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
    stroke_width: int = 0,
    stroke_fill: Optional[tuple[int, int, int, int]] = None,
) -> None:
    if stroke_width <= 0:
        draw.text(position, text, font=font, fill=fill)
        return

    outline_fill = stroke_fill or fill
    try:
        draw.text(
            position,
            text,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=outline_fill,
        )
        return
    except TypeError:
        pass

    x, y = position
    for dx, dy in _stroke_offsets(stroke_width):
        draw.text((x + dx, y + dy), text, font=font, fill=outline_fill)
    draw.text(position, text, font=font, fill=fill)


def _render_title_overlay_image(
    title_text: str,
    title_config: dict,
    video_width: int,
    video_height: int,
    template_path: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """Render title to a transparent PNG the size of the video."""
    text = _normalize_text(title_text)
    if not text:
        return None, None

    style = title_config.get("style", {})
    if style.get("uppercase", True):
        text = text.upper()

    font_path = _resolve_template_asset(style.get("font_path"), template_path) or DEFAULT_FONT_PATH
    font_size = int(style.get("font_size", DEFAULT_TITLE_FONT_SIZE))
    min_font_size = int(style.get("min_font_size", max(28, font_size // 2)))
    line_spacing = int(style.get("line_spacing", 4))

    padding_x = int(style.get("padding_x", style.get("padding", DEFAULT_TITLE_PADDING_X)))
    padding_y = int(style.get("padding_y", style.get("padding", DEFAULT_TITLE_PADDING_Y)))
    bottom_margin = int(style.get("bottom_margin", DEFAULT_TITLE_BOTTOM_MARGIN))
    max_width_ratio = float(style.get("max_width_ratio", DEFAULT_MAX_WIDTH_RATIO))
    max_height_ratio = float(style.get("max_height_ratio", 0.25))
    max_lines = int(style.get("max_lines", 0)) or 0

    max_text_width = int(video_width * max_width_ratio) - (padding_x * 2)
    max_text_width = max(300, max_text_width)
    max_text_height = int(video_height * max_height_ratio)

    img = Image.new("RGBA", (video_width, video_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font = _load_pil_font(font_path, font_size)
    lines = _wrap_text_pil(draw, text, font, max_text_width)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines - 1] + [" ".join(lines[max_lines - 1 :]).strip()]

    line_height, text_height, text_width = _measure_text_block(draw, lines, font, line_spacing)
    while (text_height + padding_y * 2) > max_text_height and font_size > min_font_size:
        font_size -= 2
        font = _load_pil_font(font_path, font_size)
        lines = _wrap_text_pil(draw, text, font, max_text_width)
        if max_lines and len(lines) > max_lines:
            lines = lines[:max_lines - 1] + [" ".join(lines[max_lines - 1 :]).strip()]
        line_height, text_height, text_width = _measure_text_block(draw, lines, font, line_spacing)

    if not lines:
        return None, None

    box_width = text_width + padding_x * 2
    box_height = text_height + padding_y * 2
    x = (video_width - box_width) // 2
    y = video_height - box_height - bottom_margin

    bg_color = style.get("bg_color", [0, 0, 0])
    bg_alpha = int(style.get("bg_alpha", 0))
    if bg_alpha > 0:
        draw.rectangle(
            [x, y, x + box_width, y + box_height],
            fill=(int(bg_color[0]), int(bg_color[1]), int(bg_color[2]), bg_alpha),
        )

    text_color = _coerce_rgba(style.get("text_color", [255, 255, 255]), (255, 255, 255))
    stroke_color = _coerce_rgba(style.get("stroke_color", [0, 0, 0]), (0, 0, 0))
    stroke_width = int(style.get("stroke_width", 0))
    shadow_alpha = int(style.get("shadow_opacity", 255))
    shadow_color = _coerce_rgba(style.get("shadow_color", [0, 0, 0]), (0, 0, 0), shadow_alpha)
    shadow_offsets = _coerce_offset_list(style.get("shadow_offsets"))
    if not shadow_offsets:
        shadow_offset = _coerce_offset(style.get("shadow_offset", 0))
        if shadow_offset != (0, 0):
            shadow_offsets = [shadow_offset]

    cursor_y = y + padding_y
    for line in lines:
        line_w = draw.textbbox((0, 0), line, font=font)[2]
        cursor_x = x + padding_x + (box_width - 2 * padding_x - line_w) // 2
        for shadow_offset in shadow_offsets:
            _draw_text_layer(
                draw,
                (cursor_x + shadow_offset[0], cursor_y + shadow_offset[1]),
                line,
                font,
                shadow_color,
                stroke_width=0,
                stroke_fill=None,
            )
        _draw_text_layer(
            draw,
            (cursor_x, cursor_y),
            line,
            font,
            text_color,
            stroke_width=stroke_width,
            stroke_fill=stroke_color,
        )
        cursor_y += line_height + line_spacing

    fd, path = tempfile.mkstemp(suffix=".png", prefix="title_overlay_")
    os.close(fd)
    img.save(path, "PNG")

    start = float(title_config.get("start", 0))
    end = title_config.get("end")
    enable_expr = None
    if end is not None:
        enable_expr = f"between(t,{start},{float(end)})"
    return path, enable_expr


def _is_image_fully_opaque(path: Optional[str]) -> bool:
    if not path or not Path(path).exists():
        return False
    try:
        with Image.open(path) as img:
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            alpha = img.split()[-1]
            min_a, max_a = alpha.getextrema()
            return min_a == 255 and max_a == 255
    except Exception:
        return False


def _truncate_word(word: str, font_path: Optional[str], font_size: int, max_width: int) -> str:
    """Truncate a word to fit within max_width."""
    for i in range(len(word), 0, -1):
        truncated = word[:i]
        if _measure_text_width(truncated, font_path, font_size) <= max_width:
            return truncated
    return word[0] if word else ""


# ─────────────────────────────────────────────────────────────────────────────
# Template loading
# ─────────────────────────────────────────────────────────────────────────────
def _load_template(template_path: Optional[str]) -> dict:
    """Load a JSON template file."""
    if not template_path:
        return {}
    path = Path(template_path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _resolve_template_asset(path: Optional[str], template_path: Optional[str]) -> Optional[str]:
    """Resolve an asset path relative to template location."""
    if not path:
        return None
    
    # Absolute path
    candidate = Path(path)
    if candidate.is_absolute() and candidate.exists():
        return str(candidate)
    
    # Relative to template
    if template_path:
        template_dir = Path(template_path).parent
        for base in [template_dir, template_dir.parent, template_dir.parent.parent]:
            resolved = base / path
            if resolved.exists():
                return str(resolved.resolve())
    
    # Relative to project
    return _resolve_path(path)


# ─────────────────────────────────────────────────────────────────────────────
# FFmpeg helpers
# ─────────────────────────────────────────────────────────────────────────────
def _get_video_duration(path: str) -> Optional[float]:
    """Get video duration in seconds using ffprobe."""
    try:
        cmd = [FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return float(result.stdout.strip())
    except Exception:
        pass
    return None


def _escape_ffmpeg_path(path: str) -> str:
    """Escape path for FFmpeg filter syntax."""
    return Path(path).as_posix().replace(":", "\\:").replace("'", "\\'")


def _write_temp_text(text: str) -> str:
    """Write text to a temporary file for FFmpeg textfile parameter."""
    fd, path = tempfile.mkstemp(suffix=".txt", prefix="title_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _run_ffmpeg(cmd: list[str], duration: Optional[float] = None, progress: bool = False) -> None:
    """Run FFmpeg command with optional progress display."""
    if not progress or not duration:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {result.stderr[:500]}")
        return

    # With progress
    cmd_with_progress = [cmd[0], "-progress", "pipe:1", "-nostats", *cmd[1:]]
    process = subprocess.Popen(
        cmd_with_progress,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    
    last_pct = -1
    total_us = int(duration * 1_000_000)
    
    for line in process.stdout or []:
        if "out_time_ms=" in line:
            try:
                value = line.split("=")[1].strip()
                out_us = int(value)
                pct = min(100, int((out_us / total_us) * 100))
                if pct // 10 != last_pct // 10:
                    print(f"[video] {pct:3d}% encoding", flush=True)
                    last_pct = pct
            except Exception:
                pass
    
    code = process.wait()
    if code != 0:
        raise RuntimeError("FFmpeg failed")


# ─────────────────────────────────────────────────────────────────────────────
# Title overlay generation
# ─────────────────────────────────────────────────────────────────────────────
def _build_title_filter(
    title_text: str,
    title_config: dict,
    video_width: int,
    video_height: int,
    template_path: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """
    Build FFmpeg drawtext filter for title overlay.
    Returns (filter_string, temp_file_path) or (None, None).
    """
    text = _normalize_text(title_text)
    if not text:
        return None, None

    style = title_config.get("style", {})
    
    # Text transform
    if style.get("uppercase", True):
        text = text.upper()

    # Font configuration
    font_path = _resolve_template_asset(style.get("font_path"), template_path) or DEFAULT_FONT_PATH
    font_size = int(style.get("font_size", DEFAULT_TITLE_FONT_SIZE))
    min_font_size = int(style.get("min_font_size", max(40, font_size // 2)))
    line_spacing = int(style.get("line_spacing", 4))

    # Layout configuration
    padding_x = int(style.get("padding_x", style.get("padding", DEFAULT_TITLE_PADDING_X)))
    padding_y = int(style.get("padding_y", style.get("padding", DEFAULT_TITLE_PADDING_Y)))
    bottom_margin = int(style.get("bottom_margin", DEFAULT_TITLE_BOTTOM_MARGIN))
    max_width_ratio = float(style.get("max_width_ratio", DEFAULT_MAX_WIDTH_RATIO))
    max_lines = int(style.get("max_lines", DEFAULT_MAX_LINES)) or DEFAULT_MAX_LINES

    # Calculate max text width (leaving room for padding on both sides)
    max_text_width = int(video_width * max_width_ratio) - (padding_x * 2)
    max_text_width = max(300, max_text_width)

    # Wrap text
    lines = _wrap_text(text, font_path, font_size, max_text_width, max_lines)
    if not lines:
        return None, None

    # Reduce font if too many lines or text too tall
    line_height = _measure_line_height(font_path, font_size)
    max_title_height = int(video_height * 0.25)  # Title can use up to 25% of height
    
    while font_size > min_font_size:
        total_height = (line_height * len(lines)) + (line_spacing * (len(lines) -1)) + (padding_y * 2)
        if total_height <= max_title_height:
            break
        font_size -= 4
        lines = _wrap_text(text, font_path, font_size, max_text_width, max_lines)
        line_height = _measure_line_height(font_path, font_size)
        if not lines:
            return None, None

    # Final text
    wrapped_text = "\n".join(lines)
    textfile_path = _write_temp_text(wrapped_text)

    # Colors
    text_color = style.get("text_color", [255, 255, 255])
    stroke_color = style.get("stroke_color", [0, 0, 0])
    stroke_width = int(style.get("stroke_width", 4))
    shadow_color = style.get("shadow_color", [0, 0, 0])
    shadow_offset_x, shadow_offset_y = _coerce_offset(style.get("shadow_offset", 2), fallback=(2, 2))
    bg_color = style.get("bg_color", [0, 0, 0])
    bg_alpha = int(style.get("bg_alpha", 0))

    def color_hex(rgb):
        return f"0x{int(rgb[0]):02x}{int(rgb[1]):02x}{int(rgb[2]):02x}"

    # Build drawtext filter
    font_opt = f":fontfile='{_escape_ffmpeg_path(font_path)}'" if font_path else ""
    
    parts = [
        f"drawtext=textfile='{_escape_ffmpeg_path(textfile_path)}'{font_opt}",
        f"fontsize={font_size}",
        f"fontcolor={color_hex(text_color)}",
        f"line_spacing={line_spacing}",
        "x=(w-text_w)/2",
        f"y=h-{bottom_margin}-text_h",
    ]

    if stroke_width > 0:
        parts.append(f"borderw={stroke_width}")
        parts.append(f"bordercolor={color_hex(stroke_color)}")

    if shadow_offset_x or shadow_offset_y:
        parts.append(f"shadowx={shadow_offset_x}")
        parts.append(f"shadowy={shadow_offset_y}")
        parts.append(f"shadowcolor={color_hex(shadow_color)}")

    # Time-based display (optional)
    start = title_config.get("start", 0)
    end = title_config.get("end")
    if end is not None:
        parts.append(f"enable='between(t,{float(start)},{float(end)})'")

    # Background box
    drawbox = None
    if bg_alpha > 0:
        box_padding_x = int(style.get("bg_padding_x", padding_x * 1.5))
        box_padding_y = int(style.get("bg_padding_y", padding_y * 1.2))
        
        max_line_width = max(_measure_text_width(line, font_path, font_size) for line in lines)
        box_w = max_line_width + (box_padding_x * 2)
        
        # Recalculate total height of text lines with spacing
        text_block_h = (line_height * len(lines)) + (line_spacing * (max(0, len(lines) - 1)))
        box_h = text_block_h + (box_padding_y * 2)
        
        box_color = f"{color_hex(bg_color)}@{bg_alpha / 255:.2f}"
        
        # Center the box and the text will be centered inside it
        box_y = f"h - {bottom_margin} - {box_h / 2} - {text_block_h / 2}"
        
        drawbox = f"drawbox=x=(w-{box_w})/2:y={box_y}:w={box_w}:h={box_h}:color={box_color}:t=fill"
        
        # Adjust text y to be centered inside the new box
        parts[-1] = f"y={box_y} + {box_padding_y}"

    drawtext = ":".join(parts)
    
    if drawbox:
        return f"{drawbox},{drawtext}", textfile_path
    return drawtext, textfile_path


# ─────────────────────────────────────────────────────────────────────────────
# Main video processing
# ─────────────────────────────────────────────────────────────────────────────
def process_video_for_instagram(
    input_path: str,
    output_path: str,
    *,
    template_path: Optional[str] = None,
    enable_subtitles: bool = False,
    quality: Optional[str] = None,
    title_text: Optional[str] = None,
    output_mode: Optional[str] = None,
) -> str:
    """
    Process a video for Instagram Reels (9:16 format).
    
    - Scales video to fit 1080x1920 with blurred background
    - Applies overlay template if provided
    - Adds title text with proper word-wrapping
    """
    quality = (quality or "normal").lower()
    if quality not in QUALITY_PRESETS:
        quality = "normal"

    duration = _get_video_duration(input_path)
    
    print(f"[video] start: {Path(input_path).name} | "
          f"duration={duration:.1f}s | quality={quality}", flush=True)

    # Load template
    template = _load_template(template_path) if template_path else {}
    title_config = template.get("title", {})
    
    # Resolve overlay image
    overlay_path = None
    bg_image = template.get("background_image")
    if bg_image:
        overlay_path = _resolve_template_asset(bg_image, template_path)
        if overlay_path and not Path(overlay_path).exists():
            overlay_path = None

    # Overlay template is always placed below the video content.

    # Build title overlay image
    title_overlay_path, title_enable = _render_title_overlay_image(
        title_text or "",
        title_config,
        REEL_WIDTH,
        REEL_HEIGHT,
        template_path,
    )

    # Build FFmpeg filter graph
    overlay_index = None
    title_index = None

    extra_inputs = []
    if overlay_path:
        overlay_index = 1
        extra_inputs.append(overlay_path)
    if title_overlay_path:
        title_index = 1 + len(extra_inputs)
        extra_inputs.append(title_overlay_path)

    filters = _build_filter_graph(
        overlay_index,
        title_index,
        title_enable,
    )

    # Quality settings
    preset_cfg = QUALITY_PRESETS[quality]
    crf = os.getenv("FFMPEG_CRF", str(preset_cfg["crf"]))
    preset = os.getenv("FFMPEG_PRESET", preset_cfg["preset"])

    # Build command
    cmd = [FFMPEG_BIN, "-y", "-i", input_path]
    
    for extra in extra_inputs:
        cmd.extend(["-i", extra])
    
    cmd.extend([
        "-filter_complex", filters,
        "-map", "[vout]",
        "-map", "0:a?",
        "-c:v", FFMPEG_VCODEC,
        "-preset", preset,
        "-crf", crf,
        "-profile:v", os.getenv("FFMPEG_PROFILE", "main"),
        "-level:v", os.getenv("FFMPEG_LEVEL", "4.1"),
        "-pix_fmt", "yuv420p",
        "-r", os.getenv("FFMPEG_OUTPUT_FPS", "30"),
        "-maxrate", os.getenv("FFMPEG_MAXRATE", "5000k"),
        "-bufsize", os.getenv("FFMPEG_BUFSIZE", "10000k"),
        "-c:a", "aac",
        "-ar", os.getenv("FFMPEG_AUDIO_RATE", "48000"),
        "-b:a", os.getenv("FFMPEG_AUDIO_BITRATE", "128k"),
        "-movflags", "+faststart",
        "-shortest",
        output_path,
    ])

    try:
        _run_ffmpeg(cmd, duration=duration, progress=VIDEO_PROGRESS)
    finally:
        if title_overlay_path:
            try:
                os.unlink(title_overlay_path)
            except Exception:
                pass

    print(f"[video] done: {Path(output_path).name}", flush=True)
    return output_path


def _build_filter_graph(
    overlay_index: Optional[int],
    title_index: Optional[int],
    title_enable: Optional[str],
) -> str:
    """
    Build FFmpeg filter graph for Instagram Reel processing.
    
    Layout:
    1. Without template: full-screen 9:16 reel with blurred background fill.
    2. With template: preserve legacy 4:5 card over a 9:16 layout.
    """
    parts = []
    if overlay_index is None:
        parts.append(
            f"[0:v]scale={REEL_WIDTH}:{REEL_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={REEL_WIDTH}:{REEL_HEIGHT},"
            f"gblur=sigma={VIDEO_BLUR_SIGMA}[bg]"
        )
        parts.append(
            f"[0:v]scale={REEL_WIDTH}:{REEL_HEIGHT}:force_original_aspect_ratio=decrease[fg]"
        )
        parts.append("[bg][fg]overlay=(W-w)/2:(H-h)/2[content]")

        current_label = "content"
        if title_index is not None:
            parts.append(f"[{title_index}:v]scale={REEL_WIDTH}:{REEL_HEIGHT}[title_img]")
            if title_enable:
                parts.append(
                    f"[{current_label}][title_img]overlay=0:0:enable='{title_enable}'[with_title]"
                )
            else:
                parts.append(f"[{current_label}][title_img]overlay=0:0[with_title]")
            current_label = "with_title"
        parts.append(f"[{current_label}]format=yuv420p,setsar=1[vout]")
        return ";".join(parts)

    content_w = REEL_WIDTH
    content_h = int(REEL_WIDTH * 5 / 4)

    parts.append(
        f"[0:v]scale={content_w}:{content_h}:force_original_aspect_ratio=increase,"
        f"crop={content_w}:{content_h},"
        f"gblur=sigma={VIDEO_BLUR_SIGMA}[bg]"
    )
    parts.append(
        f"[0:v]scale={content_w}:{content_h}:force_original_aspect_ratio=decrease,"
        f"pad={content_w}:{content_h}:(ow-iw)/2:(oh-ih)/2:color=black@0[fg]"
    )
    parts.append("[bg][fg]overlay=0:0[content]")

    current_label = "content"
    if title_index is not None:
        parts.append(f"[{title_index}:v]scale={content_w}:{content_h}[title_img]")
        if title_enable:
            parts.append(
                f"[{current_label}][title_img]overlay=0:0:enable='{title_enable}'[with_title]"
            )
        else:
            parts.append(f"[{current_label}][title_img]overlay=0:0[with_title]")
        current_label = "with_title"

    parts.append(f"[{overlay_index}:v]scale={REEL_WIDTH}:{REEL_HEIGHT}[layout]")
    y_offset = int((REEL_HEIGHT - content_h) / 2)
    parts.append(f"[layout][{current_label}]overlay=0:{y_offset}[with_layout]")
    parts.append("[with_layout]format=yuv420p,setsar=1[vout]")

    return ";".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Utility functions
# ─────────────────────────────────────────────────────────────────────────────
def get_video_duration_seconds(path: str) -> Optional[float]:
    """Public wrapper for getting video duration."""
    return _get_video_duration(path)


def _sanitize_filename(text: str, max_len: int = 80) -> str:
    """Create a safe filename from text."""
    safe = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in (text or ""))
    safe = "_".join(p for p in safe.split("_") if p)
    return (safe or "video")[:max_len]


def _download_video(url: str, output_dir: Path, slug: str, idx: int, timeout: int = 60) -> Optional[str]:
    """Download video from URL."""
    if not url:
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{_sanitize_filename(slug)}_{idx}.mp4"
    output_path = output_dir / filename
    if output_path.exists():
        return str(output_path)
    try:
        download_to_file(url, str(output_path), headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
        return str(output_path)
    except Exception as exc:
        print(f"[WARN] Video download failed: {exc}")
        return None


def download_video_if_needed(path_or_url: str, slug: str, idx: int, timeout: int = 60) -> Optional[str]:
    """Download video if it's a URL, otherwise return the path."""
    if not path_or_url:
        return None
    if str(path_or_url).startswith("http"):
        return _download_video(path_or_url, DATA_DIR / "videos", slug, idx, timeout=timeout)
    return path_or_url
