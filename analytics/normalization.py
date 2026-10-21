from __future__ import annotations

import math
from typing import Any, Dict


def _coerce_number(value: Any) -> float:
    if isinstance(value, dict):
        if "count" in value:
            return _coerce_number(value.get("count"))
        if "value" in value:
            return _coerce_number(value.get("value"))
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _first_insight_value(insights: Dict[str, Any], metric: str) -> float:
    data = insights.get(metric) or []
    if not data:
        return 0.0
    try:
        value = data[0]["values"][0]["value"]
    except Exception:
        return 0.0
    return _coerce_number(value)


def compute_performance_score(metrics: Dict[str, float]) -> float:
    views = metrics.get("views", 0.0)
    reach = metrics.get("reach", 0.0)
    impressions = metrics.get("impressions", 0.0)
    likes = metrics.get("likes", 0.0)
    comments = metrics.get("comments", 0.0)
    shares = metrics.get("shares", 0.0)
    saved = metrics.get("saved", 0.0)
    denominator = max(views, reach, impressions, 1.0)
    interaction_score = likes + (comments * 2.5) + (shares * 4.0) + (saved * 2.0)
    exposure_score = (views * 0.55) + (reach * 0.30) + (impressions * 0.15)
    normalized_interactions = interaction_score / max(math.log1p(denominator), 1.0)
    return round(exposure_score + (normalized_interactions * 18.0), 2)


def normalize_metrics(raw_metrics: Dict[str, Any], platform: str) -> Dict[str, float]:
    if platform == "instagram":
        details = raw_metrics.get("details") if isinstance(raw_metrics.get("details"), dict) else {}
        insights = raw_metrics.get("insights") if isinstance(raw_metrics.get("insights"), dict) else {}
        likes = _coerce_number(details.get("like_count")) or _first_insight_value(insights, "likes")
        comments = _coerce_number(details.get("comments_count")) or _first_insight_value(insights, "comments")
        shares = _first_insight_value(insights, "shares")
        saved = _first_insight_value(insights, "saved")
        views = max(
            _first_insight_value(insights, "plays"),
            _first_insight_value(insights, "views"),
            0.0,
        )
        reach = _first_insight_value(insights, "reach")
        impressions = _first_insight_value(insights, "impressions")
    else:
        details = raw_metrics if isinstance(raw_metrics, dict) else {}
        likes = _coerce_number(
            ((details.get("reactions") or {}).get("summary") or {}).get("total_count")
        ) or _coerce_number(
            ((details.get("likes") or {}).get("summary") or {}).get("total_count")
        )
        comments = _coerce_number(
            ((details.get("comments") or {}).get("summary") or {}).get("total_count")
        )
        shares = _coerce_number((details.get("shares") or {}).get("count"))
        saved = 0.0
        fb_insights = {
            str(item.get("name")): [item]
            for item in ((details.get("insights") or {}).get("data") or [])
            if isinstance(item, dict)
        }
        views = _coerce_number(details.get("views")) or _first_insight_value(fb_insights, "post_media_view")
        reach = _coerce_number(details.get("reach")) or _first_insight_value(fb_insights, "post_total_media_view_unique")
        impressions = _coerce_number(details.get("impressions"))
    denominator = max(views, reach, impressions, 1.0)
    engagement_rate = round(((likes + comments + shares) / denominator) * 100.0, 4)
    normalized = {
        "views": round(views, 2),
        "likes": round(likes, 2),
        "comments": round(comments, 2),
        "shares": round(shares, 2),
        "saved": round(saved, 2),
        "reach": round(reach, 2),
        "impressions": round(impressions, 2),
        "engagement_rate": engagement_rate,
    }
    normalized["performance_score"] = compute_performance_score(normalized)
    return normalized
