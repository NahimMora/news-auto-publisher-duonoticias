from __future__ import annotations

from typing import Dict, List

from storage.settings import PipelineSettings, get_settings
from storage.sqlite_store import PipelineStore


class ScoreValidationService:
    def __init__(
        self,
        store: PipelineStore,
        settings: PipelineSettings | None = None,
    ) -> None:
        self.store = store
        self.settings = settings or get_settings()

    def validate(
        self,
        *,
        lookback_days: int = 30,
        checkpoint_label: str | None = "T3",
    ) -> Dict[str, object]:
        rows = self.store.performance_rows(
            lookback_days=lookback_days,
            checkpoint_label=checkpoint_label,
            latest_only=True,
        )
        if not rows:
            payload = {
                "checkpoint_label": checkpoint_label or "latest",
                "lookback_days": lookback_days,
                "total_samples": 0,
                "correlation": 0.0,
                "accuracy_score": 0.0,
                "mean_absolute_deviation": 0.0,
                "mean_signed_deviation": 0.0,
                "overestimated_count": 0,
                "underestimated_count": 0,
                "items": [],
            }
            self.store.save_score_validation_run(payload)
            return payload
        ranked = sorted(rows, key=lambda row: float(row.get("performance_score") or 0.0))
        predicted: List[float] = []
        actual: List[float] = []
        deviations: List[float] = []
        items = []
        for index, row in enumerate(ranked):
            actual_score = 100.0 if len(ranked) == 1 else round((index / (len(ranked) - 1)) * 100.0, 2)
            predicted_score = float(row.get("score_total") or 0.0)
            deviation = round(predicted_score - actual_score, 2)
            predicted.append(predicted_score)
            actual.append(actual_score)
            deviations.append(deviation)
            items.append(
                {
                    "content_key": row.get("content_key"),
                    "source": row.get("source"),
                    "source_handle": row.get("source_handle"),
                    "score_total": predicted_score,
                    "actual_score": actual_score,
                    "performance_bucket": row.get("performance_bucket"),
                    "deviation": deviation,
                    "status": self._deviation_label(deviation),
                }
            )
        mean_abs_dev = round(sum(abs(item) for item in deviations) / len(deviations), 2)
        mean_signed_dev = round(sum(deviations) / len(deviations), 2)
        payload = {
            "checkpoint_label": checkpoint_label or "latest",
            "lookback_days": lookback_days,
            "total_samples": len(rows),
            "correlation": round(self._pearson(predicted, actual), 4),
            "accuracy_score": round(max(0.0, 100.0 - mean_abs_dev), 2),
            "mean_absolute_deviation": mean_abs_dev,
            "mean_signed_deviation": mean_signed_dev,
            "overestimated_count": sum(1 for item in deviations if item >= self.settings.score_validation_deviation_threshold),
            "underestimated_count": sum(1 for item in deviations if item <= -self.settings.score_validation_deviation_threshold),
            "items": sorted(items, key=lambda item: abs(float(item["deviation"])), reverse=True)[:20],
        }
        self.store.save_score_validation_run(payload)
        return payload

    def _deviation_label(self, deviation: float) -> str:
        threshold = self.settings.score_validation_deviation_threshold
        if deviation >= threshold:
            return "sobreestimado"
        if deviation <= -threshold:
            return "subestimado"
        return "alineado"

    @staticmethod
    def _pearson(left: List[float], right: List[float]) -> float:
        if len(left) != len(right) or len(left) < 2:
            return 0.0
        left_mean = sum(left) / len(left)
        right_mean = sum(right) / len(right)
        numerator = sum((lx - left_mean) * (rx - right_mean) for lx, rx in zip(left, right))
        left_den = sum((lx - left_mean) ** 2 for lx in left)
        right_den = sum((rx - right_mean) ** 2 for rx in right)
        if left_den <= 0 or right_den <= 0:
            return 0.0
        return numerator / ((left_den ** 0.5) * (right_den ** 0.5))
