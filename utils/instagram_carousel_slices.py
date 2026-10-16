"""Generate Instagram carousel slices with curated text."""
import json
import os
import re
import sys
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageDraw, ImageFont

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from utils.http_client import HttpClient


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


_load_dotenv(BASE_DIR / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("CAROUSEL_OPENAI_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/responses")
OPENAI_TEMPERATURE = float(os.getenv("CAROUSEL_OPENAI_TEMPERATURE", "0.4"))
OPENAI_MAX_OUTPUT_TOKENS = int(os.getenv("CAROUSEL_OPENAI_MAX_OUTPUT_TOKENS", "450"))

TEMPLATE_PATH = Path(
    os.getenv(
        "CAROUSEL_TEXT_TEMPLATE_PATH",
        str(BASE_DIR / "media" / "PlantillaPublicaciones.png"),
    )
)
FONT_PATH = Path(
    os.getenv(
        "CAROUSEL_TEXT_FONT_PATH",
        str(BASE_DIR / "media" / "TikTokSans-VariableFont_opsz,slnt,wdth,wght.ttf"),
    )
)

TARGET_SIZE = (1080, 1350)
TEXT_COLOR = (255, 255, 255)
MARGIN_X = int(os.getenv("CAROUSEL_TEXT_MARGIN_X", "120"))
MARGIN_Y = int(os.getenv("CAROUSEL_TEXT_MARGIN_Y", "240"))
LINE_SPACING = int(os.getenv("CAROUSEL_TEXT_LINE_SPACING", "12"))
BASE_FONT_SIZE = int(os.getenv("CAROUSEL_TEXT_FONT_SIZE", "46"))
MIN_FONT_SIZE = int(os.getenv("CAROUSEL_TEXT_MIN_FONT_SIZE", "32"))
MAX_CURATED_CHARS = int(os.getenv("CAROUSEL_TEXT_MAX_CHARS", "380"))
MAX_CURATED_SENTENCES = int(os.getenv("CAROUSEL_TEXT_MAX_SENTENCES", "3"))


CURATION_PROMPT = """
Sos editor periodistico para slides de Instagram. Debes resumir sin perder el sentido.
Reglas:
- Estilo informativo y neutral.
- Frases muy cortas y directas.
- Lenguaje simple y claro.
- Sin opiniones, sin emojis, sin hashtags, sin CTA, sin listas.
- No agregar datos nuevos.
- Mantener solo datos clave (quien, que, donde, cuando).
- El texto se usara en 1 o 2 slides: prioriza comprension rapida y evita saturar.
Salida: texto continuo, listo para renderizar en imagen.
Longitud obligatoria: 2 o 3 oraciones, maximo 380 caracteres.
""".strip()


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def _build_payload(text: str) -> dict:
    return {
        "model": OPENAI_MODEL,
        "temperature": OPENAI_TEMPERATURE,
        "max_output_tokens": OPENAI_MAX_OUTPUT_TOKENS,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": CURATION_PROMPT}]},
            {"role": "user", "content": [{"type": "input_text", "text": text}]},
        ],
    }


def _extract_output_text(payload: dict) -> str:
    text = (payload.get("output_text") or "").strip()
    if text:
        return text
    outputs = payload.get("output") or []
    chunks = []
    for item in outputs:
        for block in item.get("content") or []:
            if block.get("type") == "output_text" and block.get("text"):
                chunks.append(block["text"])
    return "\n".join(chunks).strip()


def _call_openai(text: str) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("Missing OPENAI_API_KEY")
    payload = _build_payload(text)
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    client = HttpClient(headers=headers, timeout=60, retries=3, backoff_base=2, backoff_max=20)
    try:
        resp = client.post(OPENAI_BASE_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()
    finally:
        client.close()
    return _extract_output_text(data)


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    words = text.split()
    if not words:
        return []
    lines = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        width = draw.textbbox((0, 0), candidate, font=font)[2]
        if width <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _load_slice_font(size: int):
    configured = str(FONT_PATH).strip()
    if configured and Path(configured).exists():
        try:
            return ImageFont.truetype(configured, size)
        except Exception:
            pass
    for fallback in ("arialn.ttf", "segoeuil.ttf", "segoeui.ttf", "calibri.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(fallback, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _text_height(draw: ImageDraw.ImageDraw, lines: List[str], font: ImageFont.FreeTypeFont) -> int:
    if not lines:
        return 0
    line_height = draw.textbbox((0, 0), "Ag", font=font)[3]
    return len(lines) * line_height + (len(lines) - 1) * LINE_SPACING


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _limit_sentences(sentences: List[str]) -> List[str]:
    limited: List[str] = []
    for sentence in sentences:
        candidate = sentence if not limited else f"{' '.join(limited)} {sentence}"
        if len(candidate) > MAX_CURATED_CHARS:
            break
        limited.append(sentence)
        if len(limited) >= MAX_CURATED_SENTENCES:
            break
    if limited:
        return limited
    if sentences:
        snippet = sentences[0][:MAX_CURATED_CHARS].rsplit(" ", 1)[0].strip()
        return [snippet or sentences[0][:MAX_CURATED_CHARS]]
    return []


def _split_into_slices(
    draw: ImageDraw.ImageDraw,
    sentences: List[str],
    font: ImageFont.FreeTypeFont,
    max_width: int,
    max_height: int,
) -> Optional[List[str]]:
    slices: List[str] = []
    current = ""

    def fits(candidate: str) -> bool:
        lines = _wrap_text(draw, candidate, font, max_width)
        return _text_height(draw, lines, font) <= max_height

    for sentence in sentences:
        candidate = sentence if not current else f"{current} {sentence}"
        if fits(candidate):
            current = candidate
            continue
        if current:
            slices.append(current)
        current = sentence
        if not fits(current):
            return None
        if len(slices) >= 2:
            return None

    if current:
        slices.append(current)
    if 1 <= len(slices) <= 2:
        return slices
    return None


def _render_slice(text: str, output_path: Path, font: ImageFont.FreeTypeFont) -> None:
    base = Image.open(TEMPLATE_PATH).convert("RGB")
    if base.size != TARGET_SIZE:
        base = base.resize(TARGET_SIZE, Image.LANCZOS)
    draw = ImageDraw.Draw(base)
    max_width = TARGET_SIZE[0] - (MARGIN_X * 2)
    max_height = TARGET_SIZE[1] - (MARGIN_Y * 2)
    lines = _wrap_text(draw, text, font, max_width)
    line_height = draw.textbbox((0, 0), "Ag", font=font)[3]
    total_height = len(lines) * line_height + (len(lines) - 1) * LINE_SPACING
    y = MARGIN_Y + max(0, (max_height - total_height) // 2)
    for line in lines:
        draw.text((MARGIN_X, y), line, font=font, fill=TEXT_COLOR)
        y += line_height + LINE_SPACING
    output_path.parent.mkdir(parents=True, exist_ok=True)
    base.save(output_path, format="PNG", optimize=True)


def create_instagram_carousel_from_news(
    image_path: str,
    raw_news_text: str,
    output_dir: str,
    slug: str,
) -> List[str]:
    if not image_path or not os.path.exists(image_path):
        return []
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Template not found: {TEMPLATE_PATH}")

    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    # Slide 1: original image (no overlays, keep original format)
    slide1 = output_dir_path / f"{slug}_01_image.png"
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        img.save(slide1, format="PNG", optimize=True)

    raw_text = _clean_text(raw_news_text)
    if not raw_text:
        return [str(slide1)]

    try:
        curated = _call_openai(raw_text)
    except Exception:
        curated = raw_text

    curated = re.sub(r"#\w+", "", curated or "")
    curated = re.sub(r"[\U00010000-\U0010ffff]", "", curated)
    curated = _clean_text(curated)
    if not curated:
        return [str(slide1)]

    sentences = _split_sentences(curated)
    sentences = _limit_sentences(sentences)
    if not sentences:
        sentences = [curated]

    slices: Optional[List[str]] = None
    font_size = BASE_FONT_SIZE
    for size in (BASE_FONT_SIZE, MIN_FONT_SIZE):
        font = _load_slice_font(size)
        temp = Image.new("RGB", TARGET_SIZE)
        draw = ImageDraw.Draw(temp)
        max_width = TARGET_SIZE[0] - (MARGIN_X * 2)
        max_height = TARGET_SIZE[1] - (MARGIN_Y * 2)
        slices = _split_into_slices(draw, sentences, font, max_width, max_height)
        if slices:
            font_size = size
            break

    if not slices:
        reduced = sentences[:]
        while len(reduced) > 1:
            reduced = reduced[:-1]
            font = _load_slice_font(BASE_FONT_SIZE)
            temp = Image.new("RGB", TARGET_SIZE)
            draw = ImageDraw.Draw(temp)
            max_width = TARGET_SIZE[0] - (MARGIN_X * 2)
            max_height = TARGET_SIZE[1] - (MARGIN_Y * 2)
            slices = _split_into_slices(draw, reduced, font, max_width, max_height)
            if slices:
                font_size = BASE_FONT_SIZE
                break

    if not slices:
        return [str(slide1)]

    slice_paths = []
    font = _load_slice_font(font_size)
    for idx, slice_text in enumerate(slices, start=2):
        out_path = output_dir_path / f"{slug}_{idx:02d}_slice.png"
        _render_slice(slice_text, out_path, font)
        slice_paths.append(str(out_path))

    return [str(slide1), *slice_paths]


def build_raw_news_text(noticia: dict) -> str:
    blocks = []
    titulo = _clean_text(noticia.get("titulo", ""))
    extracto = _clean_text(noticia.get("extracto", ""))
    if titulo:
        blocks.append(titulo)
    if extracto:
        blocks.append(extracto)
    for p in noticia.get("parrafos", []) or []:
        if isinstance(p, str) and p.strip():
            blocks.append(_clean_text(p))
    return " ".join(blocks)
