from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable

from jobs.salta_priority import is_salta_source, salta_priority_bonus
from storage.models import ViralityScore
from storage.settings import PipelineSettings, get_settings


EMOTION_TERMS = {
    "impact": 1.0,
    "viral": 0.9,
    "escandalo": 1.0,
    "escrach": 0.9,
    "ataque": 0.8,
    "furia": 0.8,
    "tension": 0.8,
    "indignacion": 0.9,
    "denuncia": 0.8,
    "acus": 0.7,
    "mato": 0.8,
    "robo": 0.8,
    "preso": 0.6,
    "viol": 0.7,
    "pelea": 0.8,
    "crisis": 0.8,
    "polém": 0.9,
    "polem": 0.9,
}

DEBATE_TERMS = {
    "milei",
    "trump",
    "izquierda",
    "derecha",
    "vegano",
    "feminismo",
    "policia",
    "inmigr",
    "cuota alimentaria",
    "villa",
    "japon",
    "seguridad",
}

REPOSTABLE_THEMES = {
    "insolito": 1.0,
    "crimen": 0.9,
    "conflicto": 0.9,
    "politica": 0.8,
    "celebridades": 0.8,
    "tendencia": 0.9,
}

CURATED_NEWS_SOURCES = {
    "tn",
    "infobae",
    "ambitofinanciero",
    "elonce",
    "minutouno",
    "noticiasargentinas",
}


def _load_json(field: str | None) -> Dict[str, Any]:
    import json

    if not field:
        return {}
    try:
        payload = json.loads(field)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def infer_theme(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("milei", "trump", "senado", "gobierno", "diput", "presidente")):
        return "politica"
    if any(token in lowered for token in ("wanda", "icardi", "tele", "show", "cantante", "actriz", "disney")):
        return "celebridades"
    if any(token in lowered for token in ("robo", "motochor", "asesin", "policia", "presa", "crimen", "delinc")):
        return "crimen"
    if any(token in lowered for token in ("viral", "tendencia", "meme", "tiktok", "twitter", "x.com")):
        return "tendencia"
    if any(token in lowered for token in ("insolito", "increible", "no podia creer", "sorpresa")):
        return "insolito"
    if any(token in lowered for token in ("pelea", "furia", "agred", "escra", "denuncia", "conflicto")):
        return "conflicto"
    return "actualidad"


def _keyword_density(text: str, dictionary: Dict[str, float]) -> float:
    lowered = text.lower()
    hits = [weight for token, weight in dictionary.items() if token in lowered]
    if not hits:
        return 0.2
    return min(1.0, 0.25 + (sum(hits) / max(1.0, len(hits))))


def _debate_density(text: str) -> float:
    lowered = text.lower()
    hits = sum(1 for term in DEBATE_TERMS if term in lowered)
    return min(1.0, 0.2 + (hits * 0.18))


def _normalize_metric(value: float, scale: float = 1000.0) -> float:
    if value <= 0:
        return 0.0
    return min(1.0, math.log1p(value) / math.log1p(scale))


def _clarity_score(title: str, summary: str) -> float:
    text = (title or summary or "").strip()
    if not text:
        return 0.2
    length = len(text)
    if 35 <= length <= 95:
        return 0.95
    if 20 <= length <= 120:
        return 0.8
    if length < 20:
        return 0.45
    return 0.55


def _duration_fit(media_type: str, duration_seconds: float | None) -> float:
    if media_type not in {"video", "reel", "carousel_video"}:
        return 0.6
    if not duration_seconds:
        return 0.55
    if 12 <= duration_seconds <= 45:
        return 1.0
    if 46 <= duration_seconds <= 75:
        return 0.85
    if 8 <= duration_seconds < 12:
        return 0.72
    if 76 <= duration_seconds <= 120:
        return 0.6
    return 0.35


class ViralityScorer:
    def __init__(self, settings: PipelineSettings | None = None) -> None:
        self.settings = settings or get_settings()

    def score_item(self, row: Dict[str, Any], recent_winners: Iterable[Dict[str, Any]] = ()) -> ViralityScore:
        title = (row.get("title") or "").strip()
        summary = (row.get("summary") or "").strip()
        body = (row.get("body_text") or "").strip()
        full_text = " ".join(part for part in (title, summary, body) if part).strip()
        media_type = (row.get("media_type") or "").strip() or "image"
        metrics = _load_json(row.get("visible_metrics_json"))
        ranking_signals = _load_json(row.get("ranking_signals_json"))
        theme = infer_theme(full_text)

        emotional_impact = _keyword_density(full_text, EMOTION_TERMS)
        debate_potential = _debate_density(full_text)
        clarity = _clarity_score(title, summary)
        duration_fit = _duration_fit(media_type, ranking_signals.get("duration_seconds"))
        topic_fit = REPOSTABLE_THEMES.get(theme, 0.58)

        views = float(metrics.get("views") or metrics.get("view_count") or 0)
        likes = float(metrics.get("likes") or metrics.get("favorite_count") or 0)
        comments = float(metrics.get("comments") or metrics.get("reply_count") or 0)
        shares = float(metrics.get("shares") or metrics.get("retweet_count") or 0)

        engagement_potential = min(
            1.0,
            0.30
            + _normalize_metric(views, 150000.0) * 0.35
            + _normalize_metric(likes + comments + shares, 12000.0) * 0.35,
        )

        novelty_base = 0.78 if (row.get("dedupe_status") or "accepted") != "discarded" else 0.15
        same_theme_hits = 0
        same_source_hits = 0
        for winner in recent_winners:
            winner_title = str(winner.get("title") or "")
            if infer_theme(winner_title) == theme:
                same_theme_hits += 1
            if str(winner.get("source") or "") == str(row.get("source") or ""):
                same_source_hits += 1
        novelty = max(0.15, novelty_base - (same_theme_hits * 0.05) - (same_source_hits * 0.03))

        repostability = min(1.0, (clarity * 0.35) + (duration_fit * 0.35) + (topic_fit * 0.30))
        source = str(row.get("source") or "").lower().strip()
        source_scores = self._source_scores(
            source=source,
            text=full_text,
            title=title,
            summary=summary,
            media_type=media_type,
            metrics=metrics,
            ranking_signals=ranking_signals,
            row=row,
        )
        safety_penalty = float(source_scores.get("safety_risk_penalty") or 0.0)
        duplication_penalty = 35.0 if (row.get("dedupe_status") or "accepted") == "discarded" else 0.0

        total = (
            novelty * 0.26
            + engagement_potential * 0.28
            + debate_potential * 0.18
            + repostability * 0.18
            + emotional_impact * 0.10
        ) * 100
        if source_scores:
            total = (total * 0.68) + (float(source_scores.get("vertical_total") or total) * 0.32)
        local_bonus = salta_priority_bonus({"source": source}, self.settings)
        total += local_bonus
        total = max(0.0, total - safety_penalty - duplication_penalty)
        total = min(100.0, total)
        total = round(total, 2)

        publish_threshold = self._source_threshold(source, "publish_threshold", self.settings.score_threshold)
        keep_floor = self._source_threshold(source, "manual_review_threshold", self.settings.score_keep_floor)
        publish = total >= publish_threshold
        if not publish and total >= keep_floor and media_type in {"video", "reel"}:
            publish = True
        news_floor = min(keep_floor, float(self.settings.score_keep_floor))
        if not publish and total >= news_floor and self._is_curated_news_post(source=source, media_type=media_type):
            publish = True

        reason = (
            f"theme={theme}, emotion={emotional_impact:.2f}, engagement={engagement_potential:.2f}, "
            f"debate={debate_potential:.2f}, duration={duration_fit:.2f}"
        )
        if local_bonus:
            reason += f", salta_priority_bonus=+{local_bonus:.1f}"
        if source == "paparazzi" and not self._paparazzi_quality_gate(source_scores):
            publish = False
            reason += ", paparazzi_quality_gate=failed"
        if source == "x" and safety_penalty >= 25.0:
            publish = False
            reason += ", x_safety_gate=failed"
        return ViralityScore(
            total=total,
            novelty=round(novelty * 100, 2),
            engagement_potential=round(engagement_potential * 100, 2),
            debate_potential=round(debate_potential * 100, 2),
            repostability=round(repostability * 100, 2),
            emotional_impact=round(emotional_impact * 100, 2),
            clarity=round(clarity * 100, 2),
            duration_fit=round(duration_fit * 100, 2),
            topic_fit=round(topic_fit * 100, 2),
            publish=publish,
            reason=reason,
            theme=theme,
            source_scores=source_scores,
        )

    def _source_scores(
        self,
        *,
        source: str,
        text: str,
        title: str,
        summary: str,
        media_type: str,
        metrics: Dict[str, Any],
        ranking_signals: Dict[str, Any],
        row: Dict[str, Any],
    ) -> Dict[str, Any]:
        if source == "x":
            return self._score_x(text, metrics, ranking_signals)
        if source == "paparazzi":
            return self._score_paparazzi(text, title, media_type, row)
        return self._score_news(text, title, summary, media_type, source)

    def _score_x(self, text: str, metrics: Dict[str, Any], ranking_signals: Dict[str, Any]) -> Dict[str, Any]:
        views = float(metrics.get("views") or metrics.get("view_count") or 0)
        likes = float(metrics.get("likes") or metrics.get("favorite_count") or 0)
        replies = float(metrics.get("replies") or metrics.get("comments") or metrics.get("reply_count") or 0)
        reposts = float(metrics.get("reposts") or metrics.get("shares") or metrics.get("retweet_count") or 0)
        bookmarks = float(metrics.get("bookmarks") or 0)
        engagement = likes + replies + reposts + bookmarks
        engagement_rate = (engagement / views) if views else 0.0
        duration = float(ranking_signals.get("duration_seconds") or 0)
        age_hours = float(ranking_signals.get("age_hours") or 0.0)
        controversy = _keyword_density(text, {"polem": 1, "escand": 1, "denuncia": 0.9, "pelea": 0.8, "furia": 0.7})
        absurdity = _keyword_density(text, {"insolito": 1, "absurdo": 1, "bizarro": 0.8, "no se puede creer": 0.9})
        safety_penalty = self._safety_penalty(text)
        raw_engagement_score = _normalize_metric(engagement, 5000) * 100
        views_score = (_normalize_metric(views, 500000) * 100) if views else min(70.0, raw_engagement_score * 0.72)
        engagement_score = min(100.0, engagement_rate * 1800) if views else raw_engagement_score
        if ranking_signals.get("velocity_score") is not None:
            velocity_score = float(ranking_signals.get("velocity_score") or 0.0)
        else:
            age_factor = 1.0 if not age_hours else max(0.25, min(1.0, 24.0 / max(age_hours, 1.0)))
            velocity_score = min(100.0, (views_score * 0.55 + engagement_score * 0.45) * age_factor)
        reel_fit_score = _duration_fit("video", duration) * 100
        vertical_total = (
            views_score * 0.20
            + engagement_score * 0.18
            + velocity_score * 0.20
            + controversy * 100 * 0.12
            + absurdity * 100 * 0.08
            + reel_fit_score * 0.14
            + _debate_density(text) * 100 * 0.08
        )
        return {
            "views_score": round(views_score, 2),
            "engagement_rate_score": round(engagement_score, 2),
            "velocity_score": round(velocity_score, 2),
            "controversy_score": round(controversy * 100, 2),
            "absurdity_score": round(absurdity * 100, 2),
            "shock_without_gore_score": round(max(0.0, controversy * 100 - safety_penalty), 2),
            "comment_potential_score": round(min(100.0, replies * 2 + controversy * 45), 2),
            "reel_fit_score": round(reel_fit_score, 2),
            "safety_risk_penalty": safety_penalty,
            "vertical_total": round(vertical_total, 2),
        }

    def _score_paparazzi(self, text: str, title: str, media_type: str, row: Dict[str, Any]) -> Dict[str, Any]:
        lowered = text.lower()
        celebrities = (
            "wanda", "icardi", "china suarez", "pampita", "tinelli", "yanina", "latorre",
            "moria", "susana", "mirtha", "tini", "lali", "gran hermano", "masterchef",
        )
        celebrity_recognition = min(100.0, 25.0 + sum(18 for name in celebrities if name in lowered))
        conflict = _keyword_density(text, {"escand": 1, "pelea": 1, "furia": 0.8, "traicion": 0.8, "separ": 0.9, "romance": 0.8})
        romance_scandal = _keyword_density(text, {"romance": 1, "separ": 1, "infiel": 1, "embarazo": 0.7, "novio": 0.6})
        tv_factor = 1.0 if any(token in lowered for token in ("telefe", "eltrece", "gran hermano", "reality", "programa")) else 0.45
        curiosity_gap = 0.85 if any(token in title.lower() for token in ("revelo", "conto", "inesperado", "sorpresa", "verdad")) else 0.45
        visual_quality = 85.0 if row.get("assets_json") else (70.0 if media_type in {"image", "carousel", "video"} else 35.0)
        comment_bait = min(100.0, conflict * 55 + celebrity_recognition * 0.35)
        freshness = self._freshness_score(row.get("created_at"))
        safety_penalty = self._safety_penalty(text)
        vertical_total = (
            celebrity_recognition * 0.24
            + conflict * 100 * 0.18
            + romance_scandal * 100 * 0.14
            + tv_factor * 100 * 0.10
            + curiosity_gap * 100 * 0.12
            + visual_quality * 0.10
            + comment_bait * 0.07
            + freshness * 0.05
        )
        return {
            "celebrity_recognition": round(celebrity_recognition, 2),
            "conflict_level": round(conflict * 100, 2),
            "romance_scandal_factor": round(romance_scandal * 100, 2),
            "tv_reality_factor": round(tv_factor * 100, 2),
            "curiosity_gap": round(curiosity_gap * 100, 2),
            "visual_material_quality": round(visual_quality, 2),
            "comment_bait_potential": round(comment_bait, 2),
            "freshness": round(freshness, 2),
            "safety_risk_penalty": safety_penalty,
            "vertical_total": round(vertical_total, 2),
        }

    def _score_news(self, text: str, title: str, summary: str, media_type: str, source: str) -> Dict[str, Any]:
        lowered = text.lower()
        public_interest = _keyword_density(text, {"seguridad": 1, "econom": 0.9, "transporte": 0.8, "salud": 0.8, "educacion": 0.7, "gobierno": 0.7})
        salta_source = is_salta_source(source, self.settings)
        local_impact = 1.0 if salta_source or any(token in lowered for token in ("salta", "jujuy", "tucuman", "norte")) else 0.35
        urgency = 1.0 if any(token in lowered for token in ("alerta", "urgente", "ahora", "paro", "corte", "temporal")) else 0.45
        practical_value = 1.0 if any(token in lowered for token in ("aumento", "tarifa", "cronograma", "inscripcion", "requisito", "como")) else 0.45
        authority = 0.92 if salta_source else (0.9 if source in {"tn", "infobae", "ambitofinanciero", "noticiasargentinas"} else 0.65)
        visual_material = 85.0 if media_type in {"image", "carousel", "video"} else 40.0
        sensitivity_penalty = self._safety_penalty(text)
        political_balance = 80.0 if any(token in lowered for token in ("gobierno", "milei", "senado", "diput")) else 95.0
        vertical_total = (
            public_interest * 100 * 0.24
            + local_impact * 100 * 0.18
            + urgency * 100 * 0.16
            + practical_value * 100 * 0.12
            + authority * 100 * 0.12
            + visual_material * 0.08
            + political_balance * 0.10
        )
        return {
            "public_interest": round(public_interest * 100, 2),
            "local_impact": round(local_impact * 100, 2),
            "salta_source_priority": bool(salta_source),
            "urgency": round(urgency * 100, 2),
            "practical_value": round(practical_value * 100, 2),
            "authority": round(authority * 100, 2),
            "visual_material": round(visual_material, 2),
            "sensitivity_risk": round(sensitivity_penalty, 2),
            "political_balance": round(political_balance, 2),
            "safety_risk_penalty": sensitivity_penalty,
            "vertical_total": round(vertical_total, 2),
        }

    @staticmethod
    def _freshness_score(value: object) -> float:
        raw = str(value or "").strip()
        if not raw:
            return 65.0
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return 65.0
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_hours = max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600)
        if age_hours <= 3:
            return 100.0
        if age_hours <= 12:
            return 85.0
        if age_hours <= 24:
            return 70.0
        if age_hours <= 72:
            return 45.0
        return 25.0

    @staticmethod
    def _safety_penalty(text: str) -> float:
        lowered = (text or "").lower()
        penalty = 0.0
        high_risk = (
            "menor",
            "menor de edad",
            "nene",
            "nena",
            "niño",
            "niña",
            "chiquito",
            "jardin",
            "jardín",
            "colegio",
            "escuela",
            "dox",
            "direccion",
            "dni",
            "desnudez",
            "violacion",
            "abuso",
        )
        graphic = ("decap", "gore", "muerte visible", "cadaver", "sangre explicita")
        if any(token in lowered for token in high_risk):
            penalty += 18.0
        if any(token in lowered for token in graphic):
            penalty += 35.0
        return penalty

    def _source_threshold(self, source: str, key: str, fallback: float) -> float:
        if key == "publish_threshold" and os.getenv("DUO_SCORE_THRESHOLD", "").strip():
            return fallback
        if key == "manual_review_threshold" and os.getenv("DUO_SCORE_KEEP_FLOOR", "").strip():
            return fallback
        thresholds = self.settings.thresholds_config if isinstance(self.settings.thresholds_config, dict) else {}
        source_thresholds = thresholds.get("source_thresholds") if isinstance(thresholds, dict) else {}
        if not isinstance(source_thresholds, dict):
            return fallback
        value = source_thresholds.get(source, {})
        if not isinstance(value, dict):
            return fallback
        try:
            return float(value.get(key, fallback))
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _paparazzi_quality_gate(scores: Dict[str, Any]) -> bool:
        celebrity = float(scores.get("celebrity_recognition") or 0.0)
        conflict = float(scores.get("conflict_level") or 0.0)
        romance = float(scores.get("romance_scandal_factor") or 0.0)
        tv = float(scores.get("tv_reality_factor") or 0.0)
        visual = float(scores.get("visual_material_quality") or 0.0)
        risk = float(scores.get("safety_risk_penalty") or 0.0)
        has_rating_hook = celebrity >= 43.0 or conflict >= 55.0 or romance >= 55.0 or tv >= 80.0
        return has_rating_hook and visual >= 50.0 and risk < 18.0

    @staticmethod
    def _is_curated_news_post(*, source: str, media_type: str) -> bool:
        normalized_media = str(media_type or "").strip().lower()
        if normalized_media in {"video", "reel", "carousel_video"}:
            return False
        return str(source or "").strip().lower() in CURATED_NEWS_SOURCES
