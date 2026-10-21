"""Adaptador del pipeline al motor audiovisual Duo Motion (carpeta motion/).

Convierte una fila editorializada en una "pieza" (contenido + presentacion,
mismo modelo que valida motion/src/schema/piece.ts) y la renderiza con un
worker Node persistente (`render/cli.ts --stdio`): sin puertos, con el bundle
y el navegador calientes durante toda la etapa de formato.

Reglas editoriales que se aplican aca, antes de llegar al render:
- El titular audiovisual sale del editorial (Gemini) o del titulo original;
  nunca se completa con texto inventado.
- Las cifras solo pasan si el numero figura literalmente en la nota.
- Los puntos clave ("Que se sabe") deben compartir la mayoria de sus palabras con
  la nota y ser cortos (<= 80 caracteres): uno largo se descarta, no se trunca.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from storage.settings import PipelineSettings

LOGGER = logging.getLogger(__name__)

CATEGORY_IDS = {
    "actualidad",
    "policiales",
    "justicia",
    "politica",
    "economia",
    "sociedad",
    "salud",
    "educacion",
    "deportes",
    "cultura",
    "espectaculos",
    "turismo",
    "clima",
    "tecnologia",
}

# Tema visual heredado del formateador -> categoria del motor.
THEME_TO_CATEGORY = {
    "showbiz": "espectaculos",
    "politics": "politica",
    "business": "economia",
    "sports": "deportes",
    "sensitive": "policiales",
}

# Nombre visible de la fuente en el diseno (la atribucion va en el layout, no en el caption).
SOURCE_NAMES = {
    "eltribuno": "El Tribuno",
    "informatesalta": "Informate Salta",
    "quepasasalta": "Qué Pasa Salta",
    "gobiernosalta": "Gobierno de Salta",
    "policiasalta": "Policía de Salta",
    "municipalidadsalta": "Municipalidad de Salta",
    "paparazzi": "Paparazzi",
    "tn": "TN",
    "infobae": "Infobae",
}

URGENT_HINTS = ("urgente", "ultimo momento", "último momento", "ahora:", "confirmaron", "alerta")


@dataclass
class MotionConfig:
    """Los reels salen solo de video real: no hay modo de foto animada (retirado 2026-10)."""

    enabled: bool
    node: str
    motion_dir: Path
    max_reel_seconds: int
    render_timeout_seconds: int
    inbox: bool
    # Musica de fondo opcional para reels: archivo local con licencia de uso (la API de Instagram
    # no permite agregar canciones de su biblioteca). Vacio = sin musica.
    music_path: str = ""
    music_volume: float = 0.12

    @classmethod
    def from_env(cls, base_dir: Path) -> "MotionConfig":
        def flag(name: str, default: str) -> bool:
            return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}

        return cls(
            enabled=flag("DUO_MOTION_ENGINE", "1"),
            node=os.getenv("DUO_MOTION_NODE", "node").strip() or "node",
            motion_dir=Path(os.getenv("DUO_MOTION_DIR", str(base_dir / "motion"))),
            max_reel_seconds=int(os.getenv("DUO_MOTION_MAX_REEL_SECONDS", "180")),
            render_timeout_seconds=int(os.getenv("DUO_MOTION_TIMEOUT_SECONDS", "300")),
            inbox=flag("DUO_MOTION_INBOX", "1"),
            music_path=os.getenv("DUO_REEL_MUSIC_PATH", "").strip(),
            music_volume=float(os.getenv("DUO_REEL_MUSIC_VOLUME", "0.12") or 0.12),
        )


class MotionUnavailable(RuntimeError):
    """El motor no esta instalado o no responde: el formateador usa el legado."""


class MotionRenderError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Worker Node
# ---------------------------------------------------------------------------


class MotionWorker:
    """Proceso `node render/cli.ts --stdio` con lectura no bloqueante."""

    def __init__(self, config: MotionConfig) -> None:
        self.config = config
        self.proc: Optional[subprocess.Popen[str]] = None
        self.events: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self.stderr_tail: List[str] = []
        self._counter = 0

    @property
    def tsx_cli(self) -> Path:
        return self.config.motion_dir / "node_modules" / "tsx" / "dist" / "cli.mjs"

    def available(self) -> bool:
        return bool(shutil.which(self.config.node)) and self.tsx_cli.exists() and (self.config.motion_dir / "render" / "cli.ts").exists()

    def start(self) -> None:
        if self.proc and self.proc.poll() is None:
            return
        if not self.available():
            raise MotionUnavailable(f"motor no instalado (node/tsx/motion en {self.config.motion_dir})")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        self.proc = subprocess.Popen(
            [self.config.node, str(self.tsx_cli), "render/cli.ts", "--stdio"],
            cwd=str(self.config.motion_dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        self.events = queue.Queue()
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        # El primer arranque puede reconstruir el bundle (~15 s).
        self._wait(lambda e: e.get("event") in {"ready", "fatal"}, timeout=180, what="arranque del motor")

    def _read_stdout(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self.events.put(json.loads(line))
            except ValueError:
                self.events.put({"event": "log", "msg": line[:300]})
        self.events.put({"event": "exit"})

    def _read_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        for line in self.proc.stderr:
            self.stderr_tail = (self.stderr_tail + [line.rstrip()])[-20:]

    def _wait(self, match, *, timeout: float, what: str) -> Dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.close(force=True)
                raise MotionRenderError(f"timeout en {what}")
            try:
                event = self.events.get(timeout=min(remaining, 5))
            except queue.Empty:
                if self.proc and self.proc.poll() is not None:
                    raise MotionUnavailable(f"el motor termino ({what}): {' | '.join(self.stderr_tail[-3:])}")
                continue
            if event.get("event") == "exit":
                raise MotionUnavailable(f"el motor termino ({what}): {' | '.join(self.stderr_tail[-3:])}")
            if event.get("event") == "fatal":
                raise MotionUnavailable(str(event.get("error") or "fatal"))
            if match(event):
                return event

    def render(self, piece: Dict[str, Any], out: Path, kind: str = "auto", *, timeout: Optional[float] = None) -> Dict[str, Any]:
        self.start()
        assert self.proc and self.proc.stdin
        self._counter += 1
        req_id = f"r{self._counter}"
        out.parent.mkdir(parents=True, exist_ok=True)
        self.proc.stdin.write(json.dumps({"id": req_id, "piece": piece, "out": str(out), "kind": kind}, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        event = self._wait(
            lambda e: e.get("id") == req_id and e.get("event") in {"done", "error"},
            timeout=timeout or self.config.render_timeout_seconds,
            what=f"render {out.name}",
        )
        if event.get("event") == "error":
            raise MotionRenderError(str(event.get("error") or "error de render"))
        return event

    def close(self, *, force: bool = False) -> None:
        proc, self.proc = self.proc, None
        if not proc:
            return
        try:
            if not force and proc.stdin:
                proc.stdin.close()
                proc.wait(timeout=15)
        except Exception:
            pass
        if proc.poll() is None:
            proc.kill()


# ---------------------------------------------------------------------------
# Contenido visual (editorial -> pieza)
# ---------------------------------------------------------------------------

_EMOJI = re.compile(r"[\U00010000-\U0010ffff☀-➿]")
_NUMBER = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?")


def _clean(text: object, limit: int = 0) -> str:
    value = _EMOJI.sub("", str(text or ""))
    value = re.sub(r"#[\w_]+", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    if limit and len(value) > limit:
        cut = value[:limit].rsplit(" ", 1)[0].rstrip(",;:")
        value = cut or value[:limit]
    return value


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _numbers_in(text: str) -> List[float]:
    values: List[float] = []
    for raw in _NUMBER.findall(text or ""):
        try:
            values.append(float(raw.replace(".", "").replace(",", ".")))
        except ValueError:
            continue
    return values


def validate_stats(stats: Iterable[Dict[str, Any]], source_text: str) -> List[Dict[str, Any]]:
    """Solo cifras cuyo valor (y el de comparacion) aparecen en la nota."""
    present = _numbers_in(source_text)

    def found(value: float) -> bool:
        return any(abs(value - p) < 1e-6 for p in present)

    out: List[Dict[str, Any]] = []
    for raw in stats or []:
        if not isinstance(raw, dict):
            continue
        try:
            value = float(str(raw.get("valor", raw.get("value"))).replace(",", "."))
        except (TypeError, ValueError):
            continue
        label = _clean(raw.get("etiqueta") or raw.get("label"), 70)
        if not label or not found(value):
            continue
        stat: Dict[str, Any] = {"label": label, "value": value, "decimals": 0 if value.is_integer() else min(2, len(str(value).split(".")[1]))}
        unit = _clean(raw.get("unidad") or raw.get("unit"), 12)
        prefix = _clean(raw.get("prefijo") or raw.get("prefix"), 4)
        if unit:
            stat["unit"] = unit
        if prefix:
            stat["prefix"] = prefix
        compare = raw.get("comparar_con", raw.get("compareValue"))
        if compare not in (None, ""):
            try:
                cval = float(str(compare).replace(",", "."))
                if found(cval):
                    stat["compareValue"] = cval
                    stat["compareLabel"] = _clean(raw.get("etiqueta_comparacion") or raw.get("compareLabel"), 30) or "Anterior"
            except (TypeError, ValueError):
                pass
        out.append(stat)
    return out[:4]


HIGHLIGHT_MAX_CHARS = 80


def validate_highlights(items: Iterable[Any], source_text: str) -> List[str]:
    """Puntos "Que se sabe": cortos y anclados en la nota (>= 60% de palabras significativas presentes)."""
    source_words = set(re.findall(r"[a-z0-9ñ]{4,}", _norm(source_text)))
    out: List[str] = []
    for item in items or []:
        text = _clean(item).rstrip(".")
        words = re.findall(r"[a-z0-9ñ]{4,}", _norm(text))
        if len(text) < 12 or len(text) > HIGHLIGHT_MAX_CHARS or not words:
            continue
        if sum(1 for w in words if w in source_words) / len(words) >= 0.6 and text not in out:
            out.append(text)
    return out[:3]


def _balanced_emphasis(headline: str) -> str:
    if headline.count("*") == 2 and re.search(r"\*[^*]{2,40}\*", headline):
        return headline
    return headline.replace("*", "")


@dataclass
class VisualBrief:
    headline: str
    deck: str
    category: str
    location: Optional[str]
    breaking: bool
    highlights: List[str] = field(default_factory=list)
    stats: List[Dict[str, Any]] = field(default_factory=list)


def extract_visual(
    editorial: Dict[str, Any],
    row: Dict[str, Any],
    raw_payload: Dict[str, Any],
    *,
    fallback_title: str,
    theme: str,
) -> VisualBrief:
    raw = editorial.get("raw_response") if isinstance(editorial.get("raw_response"), dict) else {}
    visual = raw.get("visual") if isinstance(raw.get("visual"), dict) else {}
    source_text = " ".join(
        str(x or "")
        for x in (row.get("title"), row.get("summary"), row.get("body_text"), raw_payload.get("extracto"), " ".join(raw_payload.get("parrafos") or []))
    )

    headline = _balanced_emphasis(_clean(visual.get("titular_audiovisual"), 96)) or _clean(fallback_title, 110)
    category = str(visual.get("categoria") or "").strip().lower()
    if category not in CATEGORY_IDS:
        category = THEME_TO_CATEGORY.get(theme, "")
        if not category:
            source_cat = str(raw_payload.get("categoria") or raw_payload.get("category") or "").lower()
            category = next((c for c in CATEGORY_IDS if c in _norm(source_cat)), "actualidad")
    location = _clean(visual.get("ubicacion"), 40) or None
    breaking = bool(visual.get("urgente")) if "urgente" in visual else any(h in _norm(headline) for h in URGENT_HINTS)
    deck = _clean(editorial.get("context") or row.get("summary"), 220)
    if deck and _norm(deck)[:60] == _norm(headline.replace("*", ""))[:60]:
        deck = ""
    return VisualBrief(
        headline=headline,
        deck=deck,
        category=category,
        location=location,
        breaking=breaking,
        highlights=validate_highlights(raw.get("que_se_sabe") or visual.get("claves") or [], source_text),
        stats=validate_stats(visual.get("cifras") or [], source_text),
    )


def source_display_name(row: Dict[str, Any]) -> str:
    source = str(row.get("source") or "").lower().strip()
    source_type = str(row.get("source_type") or "").lower()
    if source_type == "x_video" or source.startswith("x"):
        return "Redes sociales"
    return SOURCE_NAMES.get(source, source.title() or "Dúo Noticias")


def _iso_date(row: Dict[str, Any]) -> str:
    for key in ("created_at", "extracted_at"):
        value = str(row.get(key) or "").strip()
        if value:
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.isoformat()
            except ValueError:
                continue
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def probe_media(path: str, ffprobe: str = "ffprobe") -> Dict[str, float]:
    """Ancho, alto y duracion (si aplica) de una imagen o video local."""
    try:
        from PIL import Image

        with Image.open(path) as im:
            return {"width": float(im.width), "height": float(im.height)}
    except Exception:
        pass
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration", "-of", "json", path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        data = json.loads(out.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]
        result = {"width": float(stream.get("width") or 0), "height": float(stream.get("height") or 0)}
        duration = float((data.get("format") or {}).get("duration") or 0)
        if duration:
            result["duration"] = duration
        return result
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Motor
# ---------------------------------------------------------------------------


class MotionEngine:
    def __init__(self, settings: PipelineSettings, config: Optional[MotionConfig] = None) -> None:
        self.settings = settings
        self.config = config or MotionConfig.from_env(settings.base_dir)
        self.worker = MotionWorker(self.config)

    @property
    def enabled(self) -> bool:
        return self.config.enabled and self.worker.available()

    def close(self) -> None:
        self.worker.close()

    # -- piezas -------------------------------------------------------------

    def build_content(
        self,
        content_key: str,
        row: Dict[str, Any],
        brief: VisualBrief,
        *,
        photos: List[str] | None = None,
        video: Optional[str] = None,
    ) -> Dict[str, Any]:
        photo_entries = []
        for path in photos or []:
            meta = probe_media(path, self.settings.ffprobe_path)
            entry: Dict[str, Any] = {"src": path}
            if meta.get("width") and meta.get("height"):
                entry["width"], entry["height"] = meta["width"], meta["height"]
            photo_entries.append(entry)
        videos = []
        if video:
            meta = probe_media(video, self.settings.ffprobe_path)
            clip: Dict[str, Any] = {"src": video, "keepAudio": True, "trimStartSeconds": 0}
            if meta.get("width") and meta.get("height"):
                clip["width"], clip["height"] = meta["width"], meta["height"]
            if meta.get("duration"):
                clip["durationSeconds"] = round(meta["duration"], 2)
            videos.append(clip)
        content: Dict[str, Any] = {
            "id": content_key[:64] or "pieza",
            "originalTitle": _clean(row.get("title") or brief.headline, 240) or brief.headline,
            "headline": brief.headline,
            "deck": brief.deck,
            "category": brief.category,
            "date": _iso_date(row),
            "source": {"name": source_display_name(row), "url": str(row.get("canonical_url") or "") or None},
            "photos": photo_entries,
            "videos": videos,
            "highlights": brief.highlights,
            "stats": brief.stats,
            "breaking": brief.breaking,
            "editorialStatus": "approved",
        }
        if brief.location:
            content["location"] = brief.location
        if not content["source"]["url"]:
            content["source"].pop("url")
        return content

    # -- render -------------------------------------------------------------

    def render_reel(
        self,
        content_key: str,
        content: Dict[str, Any],
        template: str,
        out_path: Path,
        *,
        seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        video = (content.get("videos") or [None])[0]
        if not video or not video.get("src"):
            raise MotionRenderError("reel sin video real: no se generan reels de fotos")
        if seconds is None:
            seconds = float(video.get("durationSeconds") or self.config.max_reel_seconds)
        seconds = min(float(seconds), float(self.config.max_reel_seconds))
        piece = {
            "content": content,
            "presentation": {
                "template": template,
                "hook": "auto",
                "format": "reel",
                "durationSeconds": max(6.0, round(seconds, 2)),
                "theme": "light",
            },
        }
        if self.config.music_path and Path(self.config.music_path).is_file():
            piece["presentation"]["audio"] = {"src": self.config.music_path, "volume": max(0.0, min(1.0, self.config.music_volume))}
        # Render de video: ~3x tiempo real en esta PC; el timeout escala con la duracion.
        timeout = max(self.config.render_timeout_seconds, seconds * 8 + 90)
        result = self.worker.render(piece, out_path, "mp4", timeout=timeout)
        self.write_inbox(content_key, piece)
        return {"path": result.get("out") or str(out_path), "piece": piece, "ms": result.get("ms")}

    def render_cover(self, content_key: str, content: Dict[str, Any], out_path: Path) -> Dict[str, Any]:
        """Portada 9:16 del reel (plantilla "cover"): lo importante queda dentro del recorte 4:5."""
        piece = {"content": {**content, "videos": []}, "presentation": {"template": "cover", "format": "reel", "theme": "light"}}
        result = self.worker.render(piece, out_path, "jpeg")
        return {"path": result.get("out") or str(out_path), "piece": piece}

    def render_post(
        self,
        content_key: str,
        content: Dict[str, Any],
        out_dir: Path,
        *,
        extra_text_slides: List[str] | None = None,
    ) -> Dict[str, Any]:
        photos = content.get("photos") or []
        text_slides = [t for t in (extra_text_slides or []) if t.strip()]
        photo_slides = list(range(1, len(photos))) if not text_slides else []
        total = 1 + len(photo_slides) + len(text_slides)
        total = min(total, 10)
        paths: List[str] = []
        base = {"template": "static", "format": "portrait", "staticVariant": "auto", "theme": "light"}
        cover = {"content": content, "presentation": {**base, "slide": {"kind": "cover", "index": 0, "total": total}}}
        paths.append(self.worker.render(cover, out_dir / f"{content_key}_00.jpg", "jpeg")["out"])
        index = 1
        for photo_index in photo_slides:
            if index >= total:
                break
            piece = {"content": content, "presentation": {**base, "slide": {"kind": "photo", "index": photo_index, "total": total}}}
            paths.append(self.worker.render(piece, out_dir / f"{content_key}_{index:02d}.jpg", "jpeg")["out"])
            index += 1
        for text in text_slides:
            if index >= total:
                break
            piece = {"content": content, "presentation": {**base, "slide": {"kind": "text", "index": index, "total": total, "text": text}}}
            paths.append(self.worker.render(piece, out_dir / f"{content_key}_{index:02d}.jpg", "jpeg")["out"])
            index += 1
        self.write_inbox(content_key, cover)
        return {"paths": paths, "piece": cover}

    def write_inbox(self, content_key: str, piece: Dict[str, Any]) -> None:
        """Copia la pieza a motion/data/inbox para revisarla en el panel."""
        if not self.config.inbox:
            return
        try:
            inbox = self.config.motion_dir / "data" / "inbox"
            inbox.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            safe = re.sub(r"[^\w-]+", "_", content_key)[:60]
            payload = {"receivedAt": datetime.now(timezone.utc).isoformat(), "piece": piece}
            (inbox / f"{stamp}-{safe}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
            # La bandeja guarda las ultimas 200 piezas.
            files = sorted(inbox.glob("*.json"))
            for old in files[:-200]:
                old.unlink(missing_ok=True)
        except OSError as exc:
            LOGGER.warning("motion inbox: %s", exc)


def split_text_slides(text: str, max_chars: int = 340, max_slides: int = 2) -> List[str]:
    """Parte un texto curado en 1-2 slides por oraciones, sin cortar palabras."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", _clean(text)) if s.strip()]
    slides: List[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip()
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            slides.append(current)
        if len(slides) >= max_slides:
            break
        current = sentence if len(sentence) <= max_chars else _clean(sentence, max_chars)
    if current and len(slides) < max_slides:
        slides.append(current)
    return slides[:max_slides]
