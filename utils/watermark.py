"""Politica local de marcas de agua (sin IA, sin reconstruccion de imagen).

Dos casos, nada mas:

1. Marcas de agua de medios (El Tribuno, Que Pasa Salta): logo + texto blanco
   semitransparente sobre la foto o el video. Una capa blanca translucida aclara
   de forma pareja los pixeles del trazo respecto de su borde inmediato, sea cual
   sea el fondo. El detector usa la mascara real del logo (``config/watermarks``)
   como nucleo "trazo menos anillo" a varias escalas: el valor es cuanto mas
   claro esta el trazo que su contorno, y ``frac`` que parte del trazo lo esta.
   Resultado: ``clean`` / ``watermark`` (se descarta la nota) / ``ambiguous``
   (no se publica sola; queda registrada para revision). Umbrales calibrados con
   fotos reales de ambos medios (docs/REESTRUCTURACION_2026_10.md).

2. Franja azul inferior de Informate Salta: se mide fila por fila desde abajo
   cuantas filas son azul de la franja; si es una banda fina (<= 12 % del alto) se
   recorta exactamente esa altura. Si no se puede recortar limpio, el material se
   descarta.

No se borra ni se rellena nada: o se descarta, o se recorta la franja.
"""
from __future__ import annotations

import functools
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from utils.video_sanitizer import sample_frames

LOGGER = logging.getLogger("duo.watermark")
MASK_DIR = Path(__file__).resolve().parents[1] / "config" / "watermarks"
WORK_WIDTH = 600


@dataclass(frozen=True)
class BrandProfile:
    name: str
    mask_file: str
    # Ancho del logo relativo al de la imagen: rango donde la marca aparece en la practica.
    min_frac: float
    max_frac: float
    steps: int
    watermark_score: float
    watermark_frac: float
    ambiguous_score: float
    ambiguous_frac: float


BRANDS: Dict[str, BrandProfile] = {
    # El Tribuno estampa el logo entre ~50 y 70 % del ancho. Recalibrado 2026-10-18 con la fraccion
    # local: positivos 23-33 con frac >= 0.82; negativos <= 15 con frac <= 0.70.
    "eltribuno": BrandProfile("eltribuno", "eltribuno_mask.png", 0.40, 0.85, 48, 20.0, 0.78, 17.0, 0.74),
    # Que Pasa Salta varia el tamano (25-45 % del ancho). Positivos 26-32 con frac >= 0.84; el logo
    # semitransparente sobre pared clara (foto de "Salud publica", 2026-10-18) da 17.6 con frac 0.81.
    # Negativos (36 fotos de otras fuentes y sin marca) <= 27 pero siempre con frac <= 0.71: la
    # fraccion separa, por eso el puntaje minimo baja a 15 cuando frac >= 0.78.
    "quepasasalta": BrandProfile("quepasasalta", "quepasasalta_text_mask.png", 0.25, 0.75, 60, 15.0, 0.78, 21.0, 0.74),
}


# Fuente -> marcas que se buscan en su material (politica "discard" de config/sources.yaml).
SOURCE_BRANDS: Dict[str, List[str]] = {"eltribuno": ["eltribuno"], "quepasasalta": ["quepasasalta"]}


@dataclass
class WatermarkVerdict:
    status: str  # clean | watermark | ambiguous | error
    brand: str = ""
    score: float = 0.0
    reason: str = ""
    details: Dict[str, float] = field(default_factory=dict)

    @property
    def blocks(self) -> bool:
        return self.status in {"watermark", "ambiguous"}


@functools.lru_cache(maxsize=8)
def _mask(name: str) -> np.ndarray:
    path = MASK_DIR / name
    mask = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise FileNotFoundError(f"plantilla de marca de agua ausente: {path}")
    return mask


def _kernel(mask: np.ndarray, width: int) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    scale = width / mask.shape[1]
    height = max(8, int(mask.shape[0] * scale))
    glyph = cv2.resize(mask, (width, height), interpolation=cv2.INTER_AREA) > 127
    radius = max(2, int(round(width / 120)))
    dilated = cv2.dilate(glyph.astype(np.uint8), np.ones((2 * radius + 1, 2 * radius + 1), np.uint8)) > 0
    ring = dilated & ~glyph
    if not glyph.any() or not ring.any():
        return None
    kernel = np.zeros(glyph.shape, np.float32)
    kernel[glyph] = 1.0 / glyph.sum()
    kernel[ring] = -1.0 / ring.sum()
    return kernel, glyph, ring


def _local_bright_fraction(window: np.ndarray, glyph: np.ndarray, ring: np.ndarray, width: int) -> float:
    """Parte del trazo mas clara que el anillo CERCANO (no el promedio de toda la ventana): el logo
    sigue detectandose cuando pasa sobre figuras oscuras y fondo claro a la vez."""
    radius = max(2, int(round(width / 120)))
    size = 6 * radius + 1
    ring_f = ring.astype(np.float32)
    weight = cv2.blur(ring_f, (size, size))
    local = cv2.blur(window * ring_f, (size, size)) / np.maximum(weight, 1e-3)
    usable = glyph & (weight > 0.02)
    if not usable.any():
        return 0.0
    return float((window[usable] > local[usable] + 3).mean())


def brand_score(gray: np.ndarray, profile: BrandProfile) -> Tuple[float, Dict[str, float]]:
    """Maximo (brillo trazo - anillo) * fraccion de trazo aclarado, sobre escalas del perfil."""
    h, w = gray.shape[:2]
    if w != WORK_WIDTH:
        gray = cv2.resize(gray, (WORK_WIDTH, max(1, int(h * WORK_WIDTH / w))), interpolation=cv2.INTER_AREA)
    image = gray.astype(np.float32)
    h, w = image.shape
    mask = _mask(profile.mask_file)
    best = (0.0, {})
    for frac in np.geomspace(profile.min_frac, profile.max_frac, profile.steps):
        built = _kernel(mask, int(w * frac))
        if built is None:
            continue
        kernel, glyph, ring = built
        if kernel.shape[0] >= h or kernel.shape[1] >= w:
            continue
        response = cv2.filter2D(image, -1, kernel, anchor=(0, 0), borderType=cv2.BORDER_CONSTANT)
        response = response[: h - kernel.shape[0], : w - kernel.shape[1]]
        y, x = np.unravel_index(int(np.argmax(response)), response.shape)
        value = float(response[y, x])
        window = image[y : y + kernel.shape[0], x : x + kernel.shape[1]]
        bright = _local_bright_fraction(window, glyph, ring, kernel.shape[1])
        score = value * bright
        if score > best[0]:
            best = (score, {"scale": round(float(frac), 3), "x": float(x), "y": float(y), "contrast": round(value, 1), "frac": round(bright, 2)})
    return best


def verdict_for_gray(gray: np.ndarray, brands: Sequence[str]) -> WatermarkVerdict:
    worst = WatermarkVerdict(status="clean")
    for name in brands:
        profile = BRANDS.get(name)
        if profile is None:
            continue
        score, details = brand_score(gray, profile)
        frac = float(details.get("frac") or 0.0)
        if score >= profile.watermark_score and frac >= profile.watermark_frac:
            return WatermarkVerdict("watermark", name, round(score, 1), f"marca_de_agua:{name}", details)
        if score >= profile.ambiguous_score and frac >= profile.ambiguous_frac and worst.status == "clean":
            worst = WatermarkVerdict("ambiguous", name, round(score, 1), f"marca_de_agua_ambigua:{name}", details)
    return worst


def check_image(path: str, brands: Sequence[str]) -> WatermarkVerdict:
    gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return WatermarkVerdict("error", reason="imagen_ilegible")
    return verdict_for_gray(gray, brands)


def median_frame(frames: Sequence[np.ndarray]) -> Optional[np.ndarray]:
    if not frames:
        return None
    return np.median(np.stack(frames, axis=0), axis=0).astype(np.uint8)


def check_video(path: str, brands: Sequence[str], *, samples: int = 9) -> WatermarkVerdict:
    """Mediana temporal de varios cuadros: el fondo se mueve, la marca no."""
    frames = sample_frames(str(path), sample_fps=1, max_frames=samples)
    if not frames:
        return WatermarkVerdict("error", reason="video_ilegible")
    median = median_frame([cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) for frame in frames])
    verdict = verdict_for_gray(median, brands)
    if verdict.status != "clean":
        return verdict
    # Una marca puede aparecer solo en parte del video: se revisan tambien cuadros sueltos.
    for frame in frames[:: max(1, len(frames) // 3)]:
        single = verdict_for_gray(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), brands)
        if single.status == "watermark":
            return single
    return verdict


# ---------------------------------------------------------------------------
# Franja azul inferior de Informate Salta
# ---------------------------------------------------------------------------

@dataclass
class BandResult:
    found: bool
    height_px: int = 0
    frame_height: int = 0
    reason: str = ""

    @property
    def fraction(self) -> float:
        return self.height_px / self.frame_height if self.frame_height else 0.0


def _band_rows(frame_bgr: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Por fila: fraccion de pixeles con el azul de la franja (tono ~200-215 grados, saturado)."""
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0].astype(np.int16), hsv[:, :, 1], hsv[:, :, 2]
    # OpenCV: H en 0-179 (grados/2). Azul de la franja ~ 100-108.
    blue = (hue >= 96) & (hue <= 112) & (sat >= 110) & (val >= 110)
    # Las letras blancas del nombre dentro de la franja tambien cuentan como franja.
    white = (sat <= 60) & (val >= 200)
    return (blue | white).mean(axis=1), blue.mean(axis=1)


def detect_bottom_band(frames: Sequence[np.ndarray], *, max_fraction: float = 0.12) -> BandResult:
    if not frames:
        return BandResult(False, reason="sin_cuadros")
    heights: List[int] = []
    frame_height = frames[0].shape[0]
    for frame in frames:
        covered, blue = _band_rows(frame)
        rows = 0
        for index in range(frame.shape[0] - 1, -1, -1):
            # Una fila de franja es mayormente azul (o letra) y con azul real presente.
            if covered[index] >= 0.85 and blue[index] >= 0.45:
                rows += 1
                continue
            break
        heights.append(rows)
    present = [height for height in heights if height >= 4]
    if len(present) < max(2, int(len(frames) * 0.6)):
        return BandResult(False, frame_height=frame_height, reason="sin_franja")
    height = int(np.percentile(present, 90))
    if height > frame_height * max_fraction:
        return BandResult(False, height, frame_height, reason="franja_demasiado_alta")
    return BandResult(True, height, frame_height, reason="franja_informate")


def crop_bottom(video_path: str, output_path: str, pixels: int, *, ffmpeg: str = "ffmpeg", timeout: int = 300) -> str:
    """Recorta exactamente ``pixels`` filas inferiores (+2 de margen por el borde del video)."""
    cut = int(pixels) + 2
    cut += cut % 2  # libx264 exige alto par
    command = [
        ffmpeg, "-v", "error", "-y", "-i", str(video_path),
        "-vf", f"crop=iw:ih-{cut}:0:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "copy", str(output_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0 or not Path(output_path).exists():
        raise RuntimeError(f"recorte de franja fallido: {(result.stderr or '').strip()[-300:]}")
    return str(output_path)


def handle_informate_band(video_path: str, output_path: str, *, ffmpeg: str = "ffmpeg") -> Tuple[str, BandResult]:
    """Devuelve (video a usar, resultado). Sin franja: el original. Franja dudosa: RuntimeError."""
    frames = sample_frames(str(video_path), sample_fps=1, max_frames=8)
    band = detect_bottom_band(frames)
    if band.reason == "franja_demasiado_alta":
        raise RuntimeError(f"franja_no_recortable:{band.height_px}px/{band.frame_height}px")
    if not band.found:
        return str(video_path), band
    LOGGER.info("informate: franja inferior de %spx detectada en %s; se recorta", band.height_px, video_path)
    return crop_bottom(video_path, output_path, band.height_px, ffmpeg=ffmpeg), band
