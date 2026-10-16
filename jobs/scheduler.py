from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Sequence
from zoneinfo import ZoneInfo

from jobs.salta_priority import is_salta_source, salta_priority_bonus
from scoring.virality import infer_theme
from storage.models import ScheduleDecision
from storage.settings import PipelineSettings, get_settings


VIDEO_POST_TYPES = {"reel", "video"}
POST_GROUPS = ("video", "post")


@dataclass
class SlotCandidate:
    slot_label: str
    scheduled_for: datetime
    slot_bucket: str


class PeakScheduler:
    def __init__(self, settings: PipelineSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.zone = ZoneInfo(self.settings.timezone)
        self.slot_groups = {
            "experimental": {"09:00"},
            "medio": {"12:00", "15:00"},
            "alto": {"18:00", "21:00"},
        }

    def next_slots(self, count: int) -> List[SlotCandidate]:
        now = datetime.now(self.zone).replace(second=0, microsecond=0)
        slots: List[SlotCandidate] = []
        current_day = now.date()
        day_offset = 0
        while len(slots) < count:
            date_value = current_day + timedelta(days=day_offset)
            for slot in self.settings.schedule_slots:
                hour, minute = (int(part) for part in slot.split(":", 1))
                candidate = datetime(
                    year=date_value.year,
                    month=date_value.month,
                    day=date_value.day,
                    hour=hour,
                    minute=minute,
                    tzinfo=self.zone,
                )
                if not self._slot_is_schedulable(candidate, now):
                    continue
                slots.append(
                    SlotCandidate(
                        slot_label=slot,
                        scheduled_for=candidate,
                        slot_bucket=self._slot_bucket(slot),
                    )
                )
                if len(slots) >= count:
                    break
            if self.settings.publish_require_same_local_day:
                break
            day_offset += 1
        return slots

    def _slot_is_schedulable(self, candidate: datetime, now: datetime) -> bool:
        if candidate > now:
            return True
        elapsed_minutes = (now - candidate).total_seconds() / 60
        return 0 <= elapsed_minutes <= float(self.settings.publish_slot_window_minutes)

    def assign(
        self,
        rows: Iterable[Dict[str, object]],
        *,
        recent_context: Sequence[Dict[str, object]] = (),
        existing_context: Sequence[Dict[str, object]] = (),
    ) -> Dict[str, ScheduleDecision]:
        pending = [self._row_profile(row) for row in rows]
        if not pending:
            return {}
        slots = self.next_slots(max(10, len(pending), len(self.settings.schedule_slots) * 2))
        decisions: Dict[str, ScheduleDecision] = {}
        recent_profiles = self._recent_profiles(recent_context)
        slot_counts = self._existing_slot_counts(existing_context)
        priority_rank = 1
        for slot in slots:
            for post_group in POST_GROUPS:
                while self._remaining_capacity(slot, slot_counts, post_group) > 0:
                    candidates = [
                        row
                        for row in pending
                        if row["post_group"] == post_group and row["slot_bucket"] == slot.slot_bucket
                    ]
                    preferred_slot = True
                    base_constraints: List[str] = []
                    if not candidates:
                        candidates = [
                            row
                            for row in pending
                            if row["post_group"] == post_group
                            and not self._has_future_preferred_slot(row, slot, slots)
                        ]
                        preferred_slot = False
                        base_constraints = ["slot_relajado"] if candidates else []
                    if not candidates:
                        break
                    chosen, constraints = self._pick_candidate(candidates, recent_profiles)
                    constraints = [*base_constraints, *[item for item in constraints if item not in base_constraints]]
                    pending.remove(chosen)
                    content_key = str(chosen["content_key"])
                    decisions[content_key] = self._decision(
                        chosen,
                        slot,
                        priority_rank=priority_rank,
                        constraints=constraints,
                        preferred_slot=preferred_slot,
                    )
                    self._count_assignment(slot, slot_counts, post_group)
                    priority_rank += 1
                    recent_profiles.insert(0, chosen)
                    recent_profiles = recent_profiles[: self.settings.anti_fatigue_lookback_limit]
                    if not pending:
                        break
                if not pending:
                    break
            if not pending:
                break
        if pending:
            for slot in slots:
                for post_group in POST_GROUPS:
                    while self._remaining_capacity(slot, slot_counts, post_group) > 0:
                        candidates = [row for row in pending if row["post_group"] == post_group]
                        if not candidates:
                            break
                        chosen, constraints = self._pick_candidate(candidates, recent_profiles)
                        constraints = ["slot_relajado", *[item for item in constraints if item != "slot_relajado"]]
                        pending.remove(chosen)
                        content_key = str(chosen["content_key"])
                        decisions[content_key] = self._decision(
                            chosen,
                            slot,
                            priority_rank=priority_rank,
                            constraints=constraints,
                            preferred_slot=False,
                        )
                        self._count_assignment(slot, slot_counts, post_group)
                        priority_rank += 1
                        recent_profiles.insert(0, chosen)
                        recent_profiles = recent_profiles[: self.settings.anti_fatigue_lookback_limit]
                        if not pending:
                            break
                    if not pending:
                        break
                if not pending:
                    break
        return decisions

    def _decision(
        self,
        row: Dict[str, object],
        slot: SlotCandidate,
        *,
        priority_rank: int,
        constraints: List[str],
        preferred_slot: bool,
    ) -> ScheduleDecision:
        return ScheduleDecision(
            scheduled_for=self._slot_key(slot),
            slot_label=slot.slot_label,
            priority_rank=priority_rank,
            reason=self._build_reason(row, slot, constraints),
            slot_bucket=slot.slot_bucket,
            constraints=constraints,
            preferred_slot=preferred_slot,
        )

    def _pick_candidate(
        self,
        candidates: Sequence[Dict[str, object]],
        recent_profiles: Sequence[Dict[str, object]],
    ) -> tuple[Dict[str, object], List[str]]:
        ordered = sorted(candidates, key=lambda row: float(row["score_total"]), reverse=True)
        if not recent_profiles:
            return ordered[0], []
        for candidate in ordered:
            constraints = self._constraint_hits(candidate, recent_profiles)
            if not constraints:
                return candidate, []
        relaxed = max(
            ordered,
            key=lambda row: float(row["score_total"]) - (len(self._constraint_hits(row, recent_profiles)) * 8.0),
        )
        return relaxed, self._constraint_hits(relaxed, recent_profiles)

    def _constraint_hits(self, candidate: Dict[str, object], recent_profiles: Sequence[Dict[str, object]]) -> List[str]:
        hits = []
        last_profile = recent_profiles[0] if recent_profiles else {}
        if candidate["theme"] and candidate["theme"] == last_profile.get("theme"):
            hits.append("tema_repetido_consecutivo")
        if candidate["source_handle"] and candidate["source_handle"] == last_profile.get("source_handle"):
            hits.append("fuente_repetida_consecutiva")
        if candidate["post_type"] and candidate["post_type"] == last_profile.get("post_type"):
            hits.append("tipo_repetido_consecutivo")

        source_count = sum(1 for profile in recent_profiles if candidate["source_handle"] and profile.get("source_handle") == candidate["source_handle"])
        theme_count = sum(1 for profile in recent_profiles if candidate["theme"] and profile.get("theme") == candidate["theme"])
        type_count = sum(1 for profile in recent_profiles if candidate["post_type"] and profile.get("post_type") == candidate["post_type"])
        if source_count >= 2:
            hits.append("fuente_saturada")
        if theme_count >= 3:
            hits.append("tema_saturado")
        if type_count >= 3:
            hits.append("formato_saturado")
        return hits

    def _row_profile(self, row: Dict[str, object]) -> Dict[str, object]:
        base_score_total = self._score_total(row)
        priority_bonus = salta_priority_bonus(row, self.settings)
        score_total = min(100.0, base_score_total + priority_bonus)
        post_type = self._post_type(row)
        return {
            "content_key": str(row.get("content_key") or ""),
            "score_total": score_total,
            "base_score_total": base_score_total,
            "salta_priority_bonus": priority_bonus,
            "is_salta_source": is_salta_source(row.get("source"), self.settings),
            "slot_bucket": self._desired_bucket(score_total),
            "theme": str(row.get("score_theme") or infer_theme(str(row.get("title") or ""))),
            "source_handle": str(row.get("source_handle") or row.get("source") or ""),
            "post_type": post_type,
            "post_group": self._post_group(post_type),
            "title": str(row.get("title") or ""),
        }

    def _recent_profiles(self, rows: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
        profiles: List[Dict[str, object]] = []
        for row in rows[: self.settings.anti_fatigue_lookback_limit]:
            profiles.append(
                {
                    "theme": str(row.get("score_theme") or infer_theme(str(row.get("title") or ""))),
                    "source_handle": str(row.get("source_handle") or row.get("source") or ""),
                    "post_type": str(row.get("assigned_post_type") or row.get("media_type") or ""),
                }
            )
        return profiles

    def _build_reason(self, row: Dict[str, object], slot: SlotCandidate, constraints: List[str]) -> str:
        details = [
            f"score={float(row.get('base_score_total') or row['score_total']):.2f}",
            f"bucket={slot.slot_bucket}",
            f"group={row.get('post_group') or 'post'}",
        ]
        if float(row.get("salta_priority_bonus") or 0.0) > 0:
            details.append(f"prioridad_salta=+{float(row.get('salta_priority_bonus') or 0.0):.1f}")
        if constraints:
            details.append(f"restricciones={','.join(constraints)}")
        else:
            details.append("sin_repeticion_consecutiva")
        return "; ".join(details)

    def _remaining_capacity(
        self,
        slot: SlotCandidate,
        slot_counts: Dict[str, Dict[str, int]],
        post_group: str,
    ) -> int:
        if post_group == "video":
            capacity = self.settings.schedule_videos_per_slot
        else:
            capacity = self.settings.schedule_posts_per_slot
        used = slot_counts.get(self._slot_key(slot), {}).get(post_group, 0)
        return max(0, int(capacity) - int(used))

    def _count_assignment(
        self,
        slot: SlotCandidate,
        slot_counts: Dict[str, Dict[str, int]],
        post_group: str,
    ) -> None:
        key = self._slot_key(slot)
        counts = slot_counts.setdefault(key, {"video": 0, "post": 0})
        counts[post_group] = int(counts.get(post_group, 0)) + 1

    def _existing_slot_counts(self, rows: Sequence[Dict[str, object]]) -> Dict[str, Dict[str, int]]:
        counts: Dict[str, Dict[str, int]] = {}
        for row in rows:
            assigned_time = self._parse_datetime(row.get("assigned_time"))
            if assigned_time is None:
                assigned_time = self._parse_datetime(self._scheduled_for_from_json(row.get("schedule_json")))
            if assigned_time is None:
                continue
            key = assigned_time.astimezone(timezone.utc).replace(microsecond=0).isoformat()
            post_type = str(row.get("assigned_post_type") or row.get("media_type") or "")
            post_group = self._post_group(post_type)
            bucket = counts.setdefault(key, {"video": 0, "post": 0})
            bucket[post_group] = int(bucket.get(post_group, 0)) + 1
        return counts

    def _has_future_preferred_slot(
        self,
        row: Dict[str, object],
        current_slot: SlotCandidate,
        slots: Sequence[SlotCandidate],
    ) -> bool:
        current_day = current_slot.scheduled_for.date()
        for slot in slots:
            if slot.scheduled_for <= current_slot.scheduled_for:
                continue
            if slot.scheduled_for.date() != current_day:
                continue
            if slot.slot_bucket == row["slot_bucket"]:
                return True
        return False

    @staticmethod
    def _slot_key(slot: SlotCandidate) -> str:
        return slot.scheduled_for.astimezone(timezone.utc).replace(microsecond=0).isoformat()

    @staticmethod
    def _scheduled_for_from_json(raw: object) -> str:
        try:
            payload = json.loads(str(raw or ""))
        except Exception:
            return ""
        if not isinstance(payload, dict):
            return ""
        return str(payload.get("scheduled_for") or "")

    def _parse_datetime(self, value: object) -> datetime | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=self.zone)
        return dt.astimezone(self.zone)

    def _desired_bucket(self, score_total: float) -> str:
        if score_total >= self.settings.slot_high_score_min:
            return "alto"
        if score_total >= self.settings.slot_medium_score_min:
            return "medio"
        return "experimental"

    def _slot_bucket(self, slot_label: str) -> str:
        for bucket, labels in self.slot_groups.items():
            if slot_label in labels:
                return bucket
        return "medio"

    @staticmethod
    def _post_type(row: Dict[str, object]) -> str:
        raw = str(row.get("formatted_json") or "")
        if raw:
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {}
            if isinstance(payload, dict):
                value = str(payload.get("post_type") or "")
                if value:
                    return value
        return str(row.get("assigned_post_type") or row.get("media_type") or "image")

    @staticmethod
    def _post_group(post_type: str) -> str:
        return "video" if str(post_type or "").strip().lower() in VIDEO_POST_TYPES else "post"

    @staticmethod
    def _score_total(row: Dict[str, object]) -> float:
        if row.get("score_total") is not None:
            try:
                return float(row.get("score_total") or 0.0)
            except (TypeError, ValueError):
                pass
        raw = str(row.get("score_json") or "")
        try:
            payload = json.loads(raw)
        except Exception:
            return 0.0
        try:
            return float(payload.get("total") or 0.0)
        except Exception:
            return 0.0
