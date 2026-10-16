from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List
from zoneinfo import ZoneInfo

from growth.feedback import GrowthFeedbackService
from growth.source_ranking import SourceRankingService
from growth.validation import ScoreValidationService
from storage.settings import PipelineSettings, get_settings
from storage.sqlite_store import PipelineStore


class DailyReportService:
    def __init__(
        self,
        store: PipelineStore,
        feedback: GrowthFeedbackService,
        validation: ScoreValidationService,
        source_ranking: SourceRankingService,
        settings: PipelineSettings | None = None,
    ) -> None:
        self.store = store
        self.feedback = feedback
        self.validation = validation
        self.source_ranking = source_ranking
        self.settings = settings or get_settings()

    def build_report(self, report_date: date | None = None, *, write_json: bool = True) -> Dict[str, object]:
        zone = ZoneInfo(self.settings.timezone)
        target_date = report_date or datetime.now(zone).date()
        rows = []
        for row in self.store.performance_rows(lookback_days=7, latest_only=True):
            published_at = self._parse_dt(row.get("published_at"))
            if published_at is None:
                continue
            if published_at.astimezone(zone).date() == target_date:
                rows.append(row)
        ranked = sorted(rows, key=lambda row: float(row.get("performance_score") or 0.0), reverse=True)
        validation = self.validation.validate(lookback_days=30, checkpoint_label="T3")
        source_ranking = self.source_ranking.rank_sources()
        recommendations = self.feedback.build_feedback_summary()
        report = {
            "report_date": target_date.isoformat(),
            "posts_published": len(rows),
            "top_performers": [self._report_item(row) for row in ranked[:5]],
            "worst_performers": [self._report_item(row) for row in list(reversed(ranked[-5:]))],
            "published_items": [self._report_item(row) for row in ranked],
            "score_vs_performance": validation,
            "best_sources": source_ranking[:5],
            "recommendations": recommendations,
        }
        self.store.save_daily_report(target_date.isoformat(), report)
        if write_json:
            self._write_json_report(target_date, report)
        return report

    def _write_json_report(self, report_date: date, payload: Dict[str, object]) -> Path:
        self.settings.daily_report_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.settings.daily_report_dir / f"daily_report_{report_date.isoformat()}.json"
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return output_path

    @staticmethod
    def _report_item(row: Dict[str, object]) -> Dict[str, object]:
        return {
            "content_key": row.get("content_key"),
            "title": row.get("title"),
            "source": row.get("source"),
            "source_handle": row.get("source_handle"),
            "score_total": row.get("score_total"),
            "performance_score": row.get("performance_score"),
            "performance_bucket": row.get("performance_bucket"),
            "slot": row.get("assigned_slot"),
            "post_type": row.get("assigned_post_type") or row.get("post_type") or row.get("media_type"),
            "published_at": row.get("published_at"),
        }

    @staticmethod
    def _parse_dt(value: object) -> datetime | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None
