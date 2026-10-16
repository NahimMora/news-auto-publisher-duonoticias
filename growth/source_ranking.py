from __future__ import annotations

from typing import Dict, Iterable, List, Sequence

from storage.settings import PipelineSettings, get_settings
from storage.sqlite_store import PipelineStore


def _normalize_handle(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    raw = raw.replace("https://", "").replace("http://", "")
    raw = raw.replace("x.com/", "").replace("twitter.com/", "").strip("/")
    if "/" in raw:
        raw = raw.split("/", 1)[0]
    return raw.lstrip("@").strip()


class SourceRankingService:
    def __init__(
        self,
        store: PipelineStore,
        settings: PipelineSettings | None = None,
    ) -> None:
        self.store = store
        self.settings = settings or get_settings()

    def rank_sources(self, lookback_days: int | None = None) -> List[Dict[str, object]]:
        lookback = lookback_days or self.settings.source_ranking_lookback_days
        extracted_rows = self.store.source_activity_rows("x", lookback)
        performance_rows = self.store.performance_rows(lookback_days=lookback, latest_only=True)
        extracted: Dict[str, Dict[str, object]] = {}
        for row in extracted_rows:
            handle = _normalize_handle(str(row.get("source_handle") or "")) or "sin_handle"
            current = extracted.setdefault(
                handle,
                {
                    "source_handle": handle,
                    "posts_extracted": 0,
                    "posts_published": 0,
                    "average_performance": 0.0,
                    "success_rate": 0.0,
                    "priority_score": 0.0,
                },
            )
            current["posts_extracted"] = int(current["posts_extracted"]) + 1
            if str(row.get("pipeline_status") or "") == "published":
                current["posts_published"] = int(current["posts_published"]) + 1
        perf_acc: Dict[str, List[float]] = {}
        for row in performance_rows:
            handle = _normalize_handle(str(row.get("source_handle") or "")) or "sin_handle"
            perf_acc.setdefault(handle, []).append(float(row.get("performance_score") or 0.0))
        ranking: List[Dict[str, object]] = []
        for handle, item in extracted.items():
            performances = perf_acc.get(handle, [])
            avg_perf = round(sum(performances) / len(performances), 2) if performances else 0.0
            posts_extracted = int(item["posts_extracted"])
            posts_published = int(item["posts_published"])
            success_rate = round((posts_published / max(posts_extracted, 1)) * 100.0, 2)
            priority_score = round((avg_perf * 0.70) + (success_rate * 0.30), 2)
            ranking.append(
                {
                    **item,
                    "average_performance": avg_perf,
                    "success_rate": success_rate,
                    "priority_score": priority_score,
                }
            )
        ranking.sort(
            key=lambda row: (
                float(row.get("priority_score") or 0.0),
                float(row.get("average_performance") or 0.0),
                float(row.get("success_rate") or 0.0),
            ),
            reverse=True,
        )
        return ranking

    def prioritize_handles(self, handles: Sequence[str]) -> List[str]:
        cleaned = [_normalize_handle(handle) for handle in handles if handle and handle.strip()]
        cleaned = [handle for handle in cleaned if handle]
        ranking = {str(item["source_handle"]): item for item in self.rank_sources()}
        original_position = {handle: index for index, handle in enumerate(cleaned)}
        ordered = sorted(
            cleaned,
            key=lambda handle: (
                float((ranking.get(handle) or {}).get("priority_score") or -1.0),
                -original_position.get(handle, 0),
            ),
            reverse=True,
        )
        seen = set()
        result = []
        for handle in ordered:
            if handle in seen:
                continue
            seen.add(handle)
            result.append(handle)
        return result
