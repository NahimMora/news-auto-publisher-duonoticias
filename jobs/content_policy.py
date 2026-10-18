"""Filtros tecnicos y de validez, previos a cualquier evaluacion con IA.

Ya no hay listas de temas permitidos o prohibidos (politicos, famosos, palabras
clave): una nota no entra por mencionar a alguien ni sale por no hacerlo. Lo que
decide es la relevancia (``jobs/relevance.py``). Aca solo quedan restricciones
objetivas, resolubles con codigo y sin costo:

1. Origen: la fuente esta activa en ``config/sources.yaml`` (las eliminadas no pasan).
2. Validez: es una nota real (no portada de seccion, suscripcion, edicion impresa,
   vivo minuto a minuto) y tiene texto minimo.
3. Vigencia: fecha conocida y dentro de la antiguedad maxima de su grupo.
4. Elegibilidad tecnica: Paparazzi, TN e Infobae exigen un video real.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict
from zoneinfo import ZoneInfo

from storage.editorial_config import EditorialConfig, load_editorial_config
from storage.models import ExtractedContent
from storage.settings import PipelineSettings

# Paginas que no son una noticia (validez, no tema).
NON_ARTICLE_TITLES = {
    "acceso full",
    "banco de datos",
    "edicion impresa",
    "anuario autos",
    "suscripcion",
    "suscribite",
    "newsletter",
    "ultimas noticias",
    "informes especiales del gobierno de la provincia de salta",
}
_NON_ARTICLE_PATTERNS = (
    re.compile(r"^(en vivo|minuto a minuto)\b"),
    re.compile(r"\bhoroscopo de hoy\b"),
    re.compile(r"^(seccion|categoria|etiqueta)\b"),
)
# Tolerancia para relojes de servidores adelantados.
FUTURE_TOLERANCE = timedelta(hours=2)


@dataclass(frozen=True)
class ContentPolicyDecision:
    accepted: bool
    reason: str
    theme: str = ""
    created_at: str = ""


class ContentPolicy:
    def __init__(self, settings: PipelineSettings, config: EditorialConfig | None = None) -> None:
        self.settings = settings
        self.config = config or load_editorial_config(settings)
        self.zone = ZoneInfo(settings.timezone)

    def evaluate_content(self, content: ExtractedContent) -> ContentPolicyDecision:
        row = content.as_dict()
        row["assets_json"] = json.dumps([asset.as_dict() for asset in content.assets], ensure_ascii=False)
        row["raw_payload_json"] = json.dumps(content.raw_payload, ensure_ascii=False, default=str)
        return self.evaluate_row(row)

    def evaluate_row(self, row: Dict[str, Any], *, now: datetime | None = None) -> ContentPolicyDecision:
        source = str(row.get("source") or "").lower().strip()
        source_type = str(row.get("source_type") or "").lower().strip()
        if not self.config.is_enabled(source):
            return ContentPolicyDecision(False, f"fuente_inactiva:{source or 'desconocida'}")

        created_at = self._content_datetime(row)
        if created_at is None:
            return ContentPolicyDecision(False, "sin_fecha")
        now = now or datetime.now(timezone.utc)
        age = now - created_at
        if age < -FUTURE_TOLERANCE:
            return ContentPolicyDecision(False, f"fecha_futura:{created_at.isoformat()}")
        max_age = self.config.max_age_hours(source, source_type)
        if age > timedelta(hours=max_age):
            return ContentPolicyDecision(False, f"fuera_de_vigencia:{age.total_seconds() / 3600:.0f}h>{max_age:.0f}h")
        local_created = created_at.astimezone(self.zone).isoformat()

        if self._is_non_article(row):
            return ContentPolicyDecision(False, "no_es_nota", created_at=local_created)
        if self._raw_flag(row, "live_blog"):
            return ContentPolicyDecision(False, "vivo_minuto_a_minuto", created_at=local_created)
        if self._is_too_thin(row) and source_type != "x_video":
            return ContentPolicyDecision(False, "texto_insuficiente", created_at=local_created)

        has_video = self._has_video_asset(row)
        if (self.config.requires_video(source) or source_type == "x_video") and not has_video:
            return ContentPolicyDecision(False, "sin_video", created_at=local_created)
        return ContentPolicyDecision(True, f"valida; video={'si' if has_video else 'no'}", created_at=local_created)

    def today_start_utc(self) -> str:
        now = datetime.now(self.zone)
        start = datetime.combine(now.date(), time.min, tzinfo=self.zone)
        return start.astimezone(timezone.utc).replace(microsecond=0).isoformat()

    # -- chequeos -----------------------------------------------------------

    @staticmethod
    def _has_video_asset(row: Dict[str, Any]) -> bool:
        try:
            assets = json.loads(str(row.get("assets_json") or "[]"))
        except ValueError:
            return False
        return any(
            isinstance(asset, dict)
            and asset.get("kind") == "video"
            and (str(asset.get("path") or "").strip() or str(asset.get("remote_url") or "").strip())
            for asset in (assets if isinstance(assets, list) else [])
        )

    @staticmethod
    def _raw_flag(row: Dict[str, Any], key: str) -> bool:
        raw = row.get("raw_payload")
        if not isinstance(raw, dict):
            try:
                raw = json.loads(str(row.get("raw_payload_json") or "{}"))
            except ValueError:
                raw = {}
        return bool(isinstance(raw, dict) and raw.get(key))

    def _is_too_thin(self, row: Dict[str, Any]) -> bool:
        title_words = re.findall(r"\w+", _normalize(row.get("title")))
        summary_words = re.findall(r"\w+", _normalize(row.get("summary")))
        body_words = re.findall(r"\w+", _normalize(row.get("body_text")))
        return len(title_words) < 3 or (len(summary_words) + len(body_words)) < 25

    @staticmethod
    def _is_non_article(row: Dict[str, Any]) -> bool:
        title = re.sub(r"\s+", " ", _normalize(row.get("title"))).strip(" .:-")
        if not title or title in NON_ARTICLE_TITLES:
            return True
        return any(pattern.search(title) for pattern in _NON_ARTICLE_PATTERNS)

    def _content_datetime(self, row: Dict[str, Any]) -> datetime | None:
        for key in ("created_at", "detected_at"):
            dt = self._parse_datetime(row.get(key))
            if dt is not None:
                return dt
        return None

    def _parse_datetime(self, value: object) -> datetime | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        if raw.isdigit():
            try:
                return datetime.fromtimestamp(float(raw), tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self.zone)
        return dt.astimezone(timezone.utc)


def normalize_title_fingerprint(value: object) -> str:
    text = str(value or "").lower()
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:180]


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    return "".join(char for char in text if not unicodedata.combining(char))
