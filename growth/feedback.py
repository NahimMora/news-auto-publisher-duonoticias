from __future__ import annotations

import json
from collections import Counter
from typing import Dict, Iterable, List

from growth.heuristics import caption_length_bucket, classify_hook_type, classify_tone, similarity
from storage.settings import PipelineSettings, get_settings
from storage.sqlite_store import PipelineStore


class GrowthFeedbackService:
    def __init__(
        self,
        store: PipelineStore,
        settings: PipelineSettings | None = None,
    ) -> None:
        self.store = store
        self.settings = settings or get_settings()

    def build_feedback_summary(self, lookback_days: int = 21) -> str:
        rows = self.store.performance_rows(lookback_days=lookback_days, latest_only=True)
        if not rows:
            return "CONTENIDO QUE FUNCIONA:\n- Sin datos reales todavia.\nEVITAR:\n- Hooks repetidos.\n- Tono igual en todas las piezas."
        winners = [row for row in rows if str(row.get("performance_bucket") or "") in {"elite", "alto"}]
        losers = [row for row in rows if str(row.get("performance_bucket") or "") in {"bajo", "fracaso"}]
        if not winners:
            ranked = sorted(rows, key=self._performance_score, reverse=True)
            cutoff = max(1, len(ranked) // 3)
            winners = ranked[:cutoff]
        if not losers:
            ranked = sorted(rows, key=self._performance_score)
            cutoff = max(1, len(ranked) // 3)
            losers = ranked[:cutoff]
        recent_context = self.store.recent_editorial_context(self.settings.anti_fatigue_lookback_limit)
        winning_patterns = self._pattern_summary(winners)
        losing_patterns = self._pattern_summary(losers)
        fatigue_lines = self._fatigue_lines(recent_context)
        working_lines = [
            f"- Hooks que rinden: {winning_patterns['hook_types']}",
            f"- Captions que rinden: {winning_patterns['caption_lengths']}",
            f"- Tono que rinde: {winning_patterns['tones']}",
            f"- Tipo de contenido que rinde: {winning_patterns['content_types']}",
            f"- Cuentas origen que rinden: {winning_patterns['sources']}",
            f"- Slots que rinden: {winning_patterns['slots']}",
        ]
        avoid_lines = [
            f"- Hooks flojos: {losing_patterns['hook_types']}",
            f"- Captions flojas: {losing_patterns['caption_lengths']}",
            f"- Tono flojo: {losing_patterns['tones']}",
            f"- Tipo de contenido flojo: {losing_patterns['content_types']}",
            f"- Cuentas origen flojas: {losing_patterns['sources']}",
            f"- Slots flojos: {losing_patterns['slots']}",
        ]
        avoid_lines.extend(fatigue_lines)
        return "\n".join(
            [
                "CONTENIDO QUE FUNCIONA:",
                *working_lines,
                "EVITAR:",
                *avoid_lines,
            ]
        )

    def _pattern_summary(self, rows: Iterable[Dict[str, object]]) -> Dict[str, str]:
        hook_types = Counter()
        caption_lengths = Counter()
        tones = Counter()
        content_types = Counter()
        sources = Counter()
        slots = Counter()
        for row in rows:
            editorial = self._load_json(row.get("editorial_json"))
            hook = str(editorial.get("hook") or row.get("title") or "")
            caption = str(row.get("final_caption") or editorial.get("caption") or "")
            tone = str(row.get("editorial_tone") or editorial.get("tone") or "")
            hook_type = str(row.get("editorial_hook_type") or editorial.get("hook_type") or "")
            hook_types[hook_type or classify_hook_type(hook)] += 1
            caption_lengths[caption_length_bucket(caption)] += 1
            tones[tone or classify_tone(hook, caption, str(editorial.get("style") or ""))] += 1
            content_types[str(row.get("assigned_post_type") or row.get("post_type") or row.get("media_type") or "desconocido")] += 1
            sources[str(row.get("source_handle") or row.get("source") or "sin_fuente")] += 1
            slots[str(row.get("assigned_slot") or "sin_slot")] += 1
        return {
            "hook_types": self._counter_to_text(hook_types),
            "caption_lengths": self._counter_to_text(caption_lengths),
            "tones": self._counter_to_text(tones),
            "content_types": self._counter_to_text(content_types),
            "sources": self._counter_to_text(sources),
            "slots": self._counter_to_text(slots),
        }

    def _fatigue_lines(self, rows: Iterable[Dict[str, object]]) -> List[str]:
        overlays = [str(row.get("final_overlay") or "") for row in rows if row.get("final_overlay")]
        tones = Counter(str(row.get("editorial_tone") or "sin_tono") for row in rows)
        repeated_hooks = []
        for left in overlays:
            for right in overlays:
                if left == right or not left or not right:
                    continue
                if similarity(left, right) >= 0.84:
                    repeated_hooks.append(left)
                    break
        lines: List[str] = []
        if repeated_hooks:
            lines.append("- Evitar hooks muy parecidos entre si.")
        tone, tone_count = tones.most_common(1)[0] if tones else ("", 0)
        if tone and tone_count >= 3:
            lines.append(f"- Evitar abusar del tono {tone}.")
        return lines[:3]

    @staticmethod
    def _counter_to_text(counter: Counter[str]) -> str:
        if not counter:
            return "sin datos"
        return ", ".join(f"{label} ({count})" for label, count in counter.most_common(3))

    @staticmethod
    def _load_json(raw: object) -> Dict[str, object]:
        try:
            payload = json.loads(str(raw or ""))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _performance_score(row: Dict[str, object]) -> float:
        try:
            return float(row.get("performance_score") or 0.0)
        except (TypeError, ValueError):
            return 0.0
