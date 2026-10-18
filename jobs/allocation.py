"""Asignacion de cupos por ciclo horario (funcion pura, sin I/O).

Capacidad maxima por ciclo (``config/editorial_scoring.yaml``):

    local 6 | national 2 (TN + Infobae juntos) | paparazzi 2 | libres 0 | total 10

(Los cupos libres se quitaron el 2026-10-18; la logica queda por si se reactivan.)

- Los cupos son un techo, no una meta: solo entran candidatas que superaron el
  umbral de relevancia de su grupo; nada se rellena con material flojo.
- Un acontecimiento ocupa como maximo un lugar por ciclo.
- Ninguna fuente local se lleva mas de ``max_per_source_per_cycle`` de los cupos locales.
- Los videos de HolaSalta compiten por los cupos libres; si el hecho es salteno
  (relacion_salta = 2) tambien por los locales.
- Los cupos libres nunca se usan para nacionales (el tope nacional es 2).
- Una pieza publicada en Instagram y Facebook cuenta una sola vez.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

from storage.editorial_config import EditorialConfig


@dataclass
class Candidate:
    content_key: str
    group: str
    source: str
    score: float
    threshold: float
    event_key: str = ""
    salta_related: bool = False
    queue_entered_at: str = ""
    title: str = ""


@dataclass
class Allocation:
    selected: List[Dict[str, str]] = field(default_factory=list)  # {content_key, slot}
    waiting: List[str] = field(default_factory=list)
    below_threshold: List[str] = field(default_factory=list)
    reasons: Dict[str, str] = field(default_factory=dict)
    usage: Dict[str, int] = field(default_factory=dict)

    @property
    def selected_keys(self) -> List[str]:
        return [item["content_key"] for item in self.selected]


def _order(candidates: Iterable[Candidate]) -> List[Candidate]:
    # Mayor relevancia primero; a igual puntaje, la que mas espera en la cola.
    return sorted(candidates, key=lambda c: (-c.score, c.queue_entered_at or "9999"))


def allocate(
    candidates: Sequence[Candidate],
    config: EditorialConfig,
    *,
    used: Optional[Dict[str, int]] = None,
    capacity_left: Optional[int] = None,
    blocked_events: Iterable[str] = (),
) -> Allocation:
    """``used``: piezas ya ocupadas en este ciclo por cupo (local, national, paparazzi, free)."""
    used = dict(used or {})
    plan = Allocation()
    total_cap = config.max_per_cycle - sum(used.values())
    if capacity_left is not None:
        total_cap = min(total_cap, capacity_left)
    remaining = {group: max(0, quota - used.get(group, 0)) for group, quota in config.group_quotas.items()}
    remaining["free"] = max(0, config.free_slots - used.get("free", 0))
    taken_events = set(blocked_events)
    per_source: Dict[str, int] = {}

    eligible: List[Candidate] = []
    for candidate in candidates:
        if candidate.score < candidate.threshold:
            plan.below_threshold.append(candidate.content_key)
            plan.reasons[candidate.content_key] = f"bajo_umbral:{candidate.score:.0f}<{candidate.threshold:.0f}"
        else:
            eligible.append(candidate)
    pool = _order(eligible)

    def take(candidate: Candidate, slot: str, reason: str) -> None:
        nonlocal total_cap
        plan.selected.append({"content_key": candidate.content_key, "slot": slot})
        plan.reasons[candidate.content_key] = reason
        remaining[slot] -= 1
        total_cap -= 1
        if candidate.event_key:
            taken_events.add(candidate.event_key)
        if candidate.group == "local" or slot == "local":
            per_source[candidate.source] = per_source.get(candidate.source, 0) + 1

    def available(candidate: Candidate) -> bool:
        return candidate.content_key not in plan.selected_keys and not (candidate.event_key and candidate.event_key in taken_events)

    # 1) Cupos propios de cada grupo.
    for candidate in pool:
        if total_cap <= 0:
            break
        if not available(candidate):
            continue
        slot = candidate.group
        if candidate.group == "x_feed" and candidate.salta_related:
            slot = "local"
        if slot not in remaining or remaining[slot] <= 0:
            continue
        if slot == "local" and per_source.get(candidate.source, 0) >= config.max_per_source_per_cycle:
            continue
        take(candidate, slot, f"cupo_{slot}:score={candidate.score:.0f}")

    # 2) Cupos libres: lo mejor que quedo, con preferencia por lo salteno; nunca nacionales.
    leftovers = [c for c in pool if available(c) and c.group in config.free_eligible_groups and c.group != "national"]
    leftovers.sort(key=lambda c: (-(c.score + (5.0 if c.group == "local" or c.salta_related else 0.0)), c.queue_entered_at or "9999"))
    for candidate in leftovers:
        if total_cap <= 0 or remaining["free"] <= 0:
            break
        if not available(candidate):
            continue
        take(candidate, "free", f"cupo_libre:score={candidate.score:.0f}")

    for candidate in pool:
        if candidate.content_key in plan.selected_keys:
            continue
        plan.waiting.append(candidate.content_key)
        if candidate.event_key and candidate.event_key in taken_events:
            plan.reasons.setdefault(candidate.content_key, "mismo_hecho_ya_elegido")
        else:
            plan.reasons.setdefault(candidate.content_key, "sin_cupo:queda_pendiente")
    plan.usage = {slot: (config.group_quotas.get(slot, config.free_slots if slot == "free" else 0) - left) for slot, left in remaining.items()}
    return plan
