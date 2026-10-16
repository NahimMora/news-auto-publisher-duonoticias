from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List

from analytics.normalization import normalize_metrics
from publishers.meta_api import MetaGraphPublisher
from storage.settings import PipelineSettings, get_settings
from storage.sqlite_store import PipelineStore


class AnalyticsCollector:
    def __init__(
        self,
        store: PipelineStore,
        publisher: MetaGraphPublisher,
        settings: PipelineSettings | None = None,
    ) -> None:
        self.store = store
        self.publisher = publisher
        self.settings = settings or get_settings()
        self.logger = logging.getLogger("duo.analytics")

    def collect_due_snapshots(self) -> List[Dict[str, object]]:
        now_dt = datetime.now(timezone.utc).replace(microsecond=0)
        rows = self.store.list_due_analytics_checkpoints(
            now_dt,
            self.settings.analytics_checkpoint_hours,
            self.settings.analytics_lookback_hours,
        )
        snapshots: List[Dict[str, object]] = []
        touched_labels: set[str] = set()
        for row in rows:
            platform = str(row.get("platform") or "")
            media_id = str(row.get("platform_media_id") or row.get("platform_post_id") or "")
            if not media_id:
                continue
            try:
                if platform == "instagram":
                    metrics = self.publisher.collect_instagram_metrics(
                        media_id,
                        permalink=str(row.get("permalink") or ""),
                        published_at=str(row.get("published_at") or ""),
                    )
                    resolved_media_id = str(
                        ((metrics.get("meta") or {}).get("resolved_media_id") or media_id)
                    ).strip()
                    if resolved_media_id and resolved_media_id != media_id:
                        self.store.update_publication_media_id(int(row["publication_id"]), resolved_media_id)
                else:
                    metrics = self.publisher.collect_facebook_metrics(media_id)
            except Exception as exc:
                self.logger.warning(
                    "Analytics fetch failed for publication %s (%s): %s",
                    row.get("publication_id"),
                    platform,
                    exc,
                )
                continue
            if not self._has_usable_metrics(metrics, platform):
                if self._persist_unavailable_snapshot(row, metrics, platform):
                    continue
                self.logger.warning(
                    "Analytics unavailable for publication %s (%s); skipping checkpoint %s",
                    row.get("publication_id"),
                    platform,
                    row.get("checkpoint_label"),
                )
                continue
            normalized = normalize_metrics(metrics, platform)
            checkpoint_label = str(row.get("checkpoint_label") or "")
            self.store.save_analytics_snapshot(
                int(row["publication_id"]),
                metrics,
                checkpoint_label=checkpoint_label,
                checkpoint_order=int(row.get("checkpoint_order") or 0),
                due_at=str(row.get("due_at") or ""),
                publication_age_minutes=int(row.get("publication_age_minutes") or 0),
                views=int(normalized.get("views") or 0),
                likes=int(normalized.get("likes") or 0),
                comments=int(normalized.get("comments") or 0),
                shares=int(normalized.get("shares") or 0),
                engagement_rate=float(normalized.get("engagement_rate") or 0.0),
                performance_score=float(normalized.get("performance_score") or 0.0),
            )
            snapshots.append(
                {
                    "publication_id": row["publication_id"],
                    "platform": platform,
                    "checkpoint": checkpoint_label,
                    "metrics": normalized,
                }
            )
            if checkpoint_label:
                touched_labels.add(checkpoint_label)
        for checkpoint_label in touched_labels:
            self._rebucket_checkpoint(checkpoint_label)
        return snapshots

    @staticmethod
    def _has_usable_metrics(metrics: Dict[str, object], platform: str) -> bool:
        if platform == "instagram":
            details = metrics.get("details") if isinstance(metrics.get("details"), dict) else {}
            insights = metrics.get("insights") if isinstance(metrics.get("insights"), dict) else {}
            return bool(details) or any(bool(value) for value in insights.values())
        return bool(metrics)

    def _persist_unavailable_snapshot(
        self,
        row: Dict[str, object],
        metrics: Dict[str, object],
        platform: str,
    ) -> bool:
        if platform != "instagram" or not self._is_terminal_instagram_unavailable(metrics):
            return False
        snapshot_metrics = dict(metrics)
        meta = dict(snapshot_metrics.get("meta") or {})
        meta["analytics_status"] = "unavailable"
        meta["unavailable_reason"] = "instagram_media_unavailable"
        snapshot_metrics["meta"] = meta
        self.store.save_analytics_snapshot(
            int(row["publication_id"]),
            snapshot_metrics,
            checkpoint_label=str(row.get("checkpoint_label") or ""),
            checkpoint_order=int(row.get("checkpoint_order") or 0),
            due_at=str(row.get("due_at") or ""),
            publication_age_minutes=int(row.get("publication_age_minutes") or 0),
            views=0,
            likes=0,
            comments=0,
            shares=0,
            engagement_rate=0.0,
            performance_score=0.0,
        )
        self.logger.info(
            "Analytics unavailable permanently for publication %s (%s); checkpoint %s marked unavailable",
            row.get("publication_id"),
            platform,
            row.get("checkpoint_label"),
        )
        return True

    @staticmethod
    def _is_terminal_instagram_unavailable(metrics: Dict[str, object]) -> bool:
        errors = metrics.get("errors") if isinstance(metrics.get("errors"), dict) else {}
        detail_error = str(errors.get("details") or "").lower()
        return "unsupported get request" in detail_error and "error_subcode" in detail_error and "33" in detail_error

    def _rebucket_checkpoint(self, checkpoint_label: str) -> None:
        rows = self.store.analytics_scores(checkpoint_label)
        if not rows:
            return
        total = len(rows)
        for index, row in enumerate(rows):
            percentile = 1.0 if total == 1 else index / (total - 1)
            bucket = self._bucket_for_percentile(percentile)
            snapshot_id = int(row["id"])
            self.store.update_analytics_bucket(snapshot_id, bucket)
            self.store.refresh_content_performance(int(row["publication_id"]))

    def _bucket_for_percentile(self, percentile: float) -> str:
        if percentile >= self.settings.bucket_elite_percentile:
            return "elite"
        if percentile >= self.settings.bucket_high_percentile:
            return "alto"
        if percentile >= self.settings.bucket_medium_percentile:
            return "medio"
        if percentile >= self.settings.bucket_low_percentile:
            return "bajo"
        return "fracaso"
