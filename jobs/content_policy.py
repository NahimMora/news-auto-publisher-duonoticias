from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, time, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict
from zoneinfo import ZoneInfo

from scoring.virality import infer_theme
from storage.models import ExtractedContent
from storage.settings import PipelineSettings


POLITICS_TERMS = {
    "milei",
    "politica",
    "politico",
    "gobierno",
    "presidente",
    "congreso",
    "senado",
    "diputado",
    "diputada",
    "ministro",
    "ministra",
    "villarruel",
    "adorni",
    "caputo",
    "trump",
    "iran",
    "israel",
    "kicillof",
    "eleccion",
    "campana",
    "justicia",
    "ley",
    "reforma",
}

CRIME_TERMS = {
    "policia",
    "policial",
    "policiales",
    "detenido",
    "detuvieron",
    "allanamiento",
    "robo",
    "motochorro",
    "delincuente",
    "banda",
    "narco",
    "droga",
    "crimen",
    "asesin",
    "homicidio",
    "profugo",
    "violencia",
    "balearon",
    "disparo",
    "secuestro",
    "estafa",
}

ENTERTAINMENT_TERMS = {
    "wanda",
    "icardi",
    "china suarez",
    "pampita",
    "tinelli",
    "yanina",
    "latorre",
    "moria",
    "susana",
    "mirtha",
    "tini",
    "lali",
    "telefe",
    "eltrece",
    "espectaculo",
    "espectaculos",
    "farandula",
    "gran hermano",
    "masterchef",
    "novela",
    "actor",
    "actriz",
    "cantante",
    "famoso",
    "famosa",
    "romance",
    "separacion",
}

PUBLIC_SAFETY_TERMS = {
    "alerta",
    "salud",
    "riesgo",
    "adulterado",
    "adulterada",
    "intoxic",
    "contamin",
    "brote",
    "hospital",
    "toxico",
    "veneno",
    "consumidor",
}

BLOCKED_LOW_VALUE_TERMS = {
    "horoscopo",
    "zodiaco",
    "signos",
    "premier league",
    "la liga",
    "formaciones",
    "dolar blue",
    "cotizan",
    "acceso full",
    "suscripcion",
    "suscripción",
    "edicion impresa",
    "edición impresa",
    "banco de datos",
    "anuario autos",
    "fixture",
    "minuto a minuto",
}

LOW_VALUE_EXACT_TITLES = {
    "acceso full",
    "banco de datos",
    "edicion impresa",
    "edición impresa",
    "mundial 2026",
    "seleccion argentina",
    "selección argentina",
}


@dataclass(frozen=True)
class ContentPolicyDecision:
    accepted: bool
    reason: str
    theme: str = ""
    created_at: str = ""


class ContentPolicy:
    def __init__(self, settings: PipelineSettings) -> None:
        self.settings = settings
        self.zone = ZoneInfo(settings.timezone)

    def evaluate_content(self, content: ExtractedContent) -> ContentPolicyDecision:
        row = content.as_dict()
        row["assets_json"] = json.dumps([asset.as_dict() for asset in content.assets], ensure_ascii=False)
        return self.evaluate_row(row)

    def evaluate_row(self, row: Dict[str, Any]) -> ContentPolicyDecision:
        source = str(row.get("source") or "").lower().strip()
        if source and not self._source_enabled(source):
            return ContentPolicyDecision(False, f"disabled_source:{source}")

        same_day_required = self._requires_same_local_day(row)
        created_at = self._content_datetime(row)
        if created_at is None:
            return ContentPolicyDecision(False, "missing_created_at")
        local_created = created_at.astimezone(self.zone)
        if same_day_required and local_created.date() != datetime.now(self.zone).date():
            return ContentPolicyDecision(False, f"not_from_today:{local_created.date().isoformat()}")
        scheduled_at = self._scheduled_datetime(row)
        if same_day_required and scheduled_at is not None:
            if scheduled_at.astimezone(self.zone).date() != local_created.date():
                return ContentPolicyDecision(False, "scheduled_day_mismatch")

        media_type = str(row.get("assigned_post_type") or row.get("media_type") or "").strip().lower()
        if same_day_required and media_type in {"video", "reel"} and local_created.date() != datetime.now(self.zone).date():
            return ContentPolicyDecision(False, "video_not_from_today")
        if self._is_too_thin(row):
            return ContentPolicyDecision(False, "thin_content")
        if self._is_low_value_page(row):
            return ContentPolicyDecision(False, "low_value_page")

        text = self._combined_text(row)
        theme = infer_theme(text)
        if media_type in {"video", "reel"}:
            return ContentPolicyDecision(
                True,
                f"video_topic_bypass; theme={theme}; created_at={local_created.isoformat()}",
                theme=theme,
                created_at=local_created.isoformat(),
            )
        topic = self._topic(text, row)
        if not topic:
            return ContentPolicyDecision(False, f"topic_not_allowed:{theme}", theme=theme, created_at=local_created.isoformat())
        return ContentPolicyDecision(True, f"topic={topic}; created_at={local_created.isoformat()}", theme=theme, created_at=local_created.isoformat())

    def today_start_utc(self) -> str:
        now = datetime.now(self.zone)
        start = datetime.combine(now.date(), time.min, tzinfo=self.zone)
        return start.astimezone(timezone.utc).replace(microsecond=0).isoformat()

    def _topic(self, text: str, row: Dict[str, Any]) -> str:
        lowered = _normalize_for_match(text)
        headline = _normalize_for_match(self._headline_text(row))
        source = str(row.get("source") or "").lower().strip()
        if _has_any_term(lowered, BLOCKED_LOW_VALUE_TERMS):
            if not _has_any_term(lowered, POLITICS_TERMS | CRIME_TERMS | ENTERTAINMENT_TERMS | PUBLIC_SAFETY_TERMS):
                return ""
        if _has_any_term(headline, POLITICS_TERMS):
            return "politica"
        if _has_any_term(headline, CRIME_TERMS):
            return "policiales"
        if _has_any_term(headline, ENTERTAINMENT_TERMS):
            return "espectaculos"
        if _has_any_term(headline, PUBLIC_SAFETY_TERMS):
            return "alerta_publica"
        tags = _normalize_for_match(self._tags_text(row))
        if source == "paparazzi" and (_has_any_term(lowered, ENTERTAINMENT_TERMS) or _has_any_term(tags, ENTERTAINMENT_TERMS)):
            return "espectaculos"
        return ""

    def _headline_text(self, row: Dict[str, Any]) -> str:
        return " ".join(
            str(value or "")
            for value in (
                row.get("title"),
                row.get("summary"),
                self._tags_text(row),
            )
        )

    def _is_too_thin(self, row: Dict[str, Any]) -> bool:
        title_words = re.findall(r"\w+", _normalize_for_match(row.get("title")))
        summary_words = re.findall(r"\w+", _normalize_for_match(row.get("summary")))
        body_words = re.findall(r"\w+", _normalize_for_match(row.get("body_text")))
        if len(title_words) < 3 and len(summary_words) < 8 and len(body_words) < 20:
            return True
        return False

    def _is_low_value_page(self, row: Dict[str, Any]) -> bool:
        title = _normalize_for_match(row.get("title"))
        title = re.sub(r"\s+", " ", title).strip()
        if title in {_normalize_for_match(item) for item in LOW_VALUE_EXACT_TITLES}:
            return True
        text = _normalize_for_match(self._combined_text(row))
        if _has_any_term(text, BLOCKED_LOW_VALUE_TERMS):
            relevant_terms = POLITICS_TERMS | CRIME_TERMS | ENTERTAINMENT_TERMS | PUBLIC_SAFETY_TERMS
            return not _has_any_term(text, relevant_terms)
        return False

    def _source_enabled(self, source: str) -> bool:
        sources = self.settings.sources_config.get("sources") if isinstance(self.settings.sources_config, dict) else None
        if not isinstance(sources, list):
            return True
        for item in sources:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").lower().strip()
            if name == source:
                return item.get("enabled") is not False
        return True

    def _requires_same_local_day(self, row: Dict[str, Any]) -> bool:
        source = str(row.get("source") or "").lower().strip()
        source_type = str(row.get("source_type") or "").lower().strip()
        if source in {"x", "x_manual"} or source_type == "x_video":
            return self.settings.x_require_same_local_day
        return self.settings.publish_require_same_local_day

    def _combined_text(self, row: Dict[str, Any]) -> str:
        values = [
            row.get("title"),
            row.get("summary"),
            row.get("body_text"),
            row.get("source"),
            row.get("source_handle"),
            self._tags_text(row),
        ]
        return " ".join(str(value or "") for value in values)

    @staticmethod
    def _tags_text(row: Dict[str, Any]) -> str:
        raw = row.get("tags_json")
        if not raw:
            return ""
        try:
            payload = json.loads(str(raw))
        except Exception:
            return str(raw)
        if isinstance(payload, list):
            return " ".join(str(item) for item in payload)
        return str(payload)

    def _content_datetime(self, row: Dict[str, Any]) -> datetime | None:
        for key in ("created_at", "detected_at", "extracted_at"):
            dt = self._parse_datetime(row.get(key))
            if dt is not None:
                return dt
        return None

    def _scheduled_datetime(self, row: Dict[str, Any]) -> datetime | None:
        for key in ("assigned_time", "scheduled_for"):
            dt = self._parse_datetime(row.get(key))
            if dt is not None:
                return dt
        try:
            schedule = json.loads(str(row.get("schedule_json") or "{}"))
        except Exception:
            schedule = {}
        if isinstance(schedule, dict):
            return self._parse_datetime(schedule.get("scheduled_for"))
        return None

    def _parse_datetime(self, value: object) -> datetime | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        if raw.isdigit():
            try:
                return datetime.fromtimestamp(float(raw), tz=timezone.utc)
            except Exception:
                return None
        normalized = raw.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            try:
                dt = parsedate_to_datetime(raw)
            except Exception:
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


def _normalize_for_match(value: object) -> str:
    text = str(value or "").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return text


def _has_any_term(text: str, terms: set[str]) -> bool:
    for term in terms:
        normalized = _normalize_for_match(term)
        if re.search(rf"(?<!\w){re.escape(normalized)}(?!\w)", text):
            return True
    return False
