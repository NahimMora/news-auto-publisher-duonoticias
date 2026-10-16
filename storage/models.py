from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


@dataclass
class Asset:
    kind: str
    path: str = ""
    remote_url: str = ""
    mime_type: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    duration_seconds: Optional[float] = None
    sha1: str = ""
    perceptual_hash: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExtractedContent:
    source: str
    source_type: str
    source_item_id: str
    canonical_url: str
    author: str = ""
    source_handle: str = ""
    title: str = ""
    summary: str = ""
    body_text: str = ""
    language: str = "es"
    media_type: str = "image"
    created_at: str = ""
    extracted_at: str = field(default_factory=utc_now_iso)
    visible_metrics: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    ranking_signals: Dict[str, Any] = field(default_factory=dict)
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    assets: List[Asset] = field(default_factory=list)
    content_key: str = ""

    def ensure_content_key(self) -> str:
        if self.content_key:
            return self.content_key
        base = "|".join(
            part
            for part in (
                self.source,
                self.source_type,
                self.source_item_id,
                self.canonical_url,
                compact_text(self.title)[:120],
            )
            if part
        )
        if not base:
            base = safe_json(self.raw_payload)
        self.content_key = hashlib.sha1(base.encode("utf-8")).hexdigest()
        return self.content_key

    def combined_text(self) -> str:
        return "\n".join(
            value
            for value in (
                compact_text(self.title),
                compact_text(self.summary),
                compact_text(self.body_text),
            )
            if value
        )

    def as_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["content_key"] = self.ensure_content_key()
        return payload


@dataclass
class DedupDecision:
    status: str
    reason: str
    matched_content_key: str = ""
    perceptual_hash: str = ""


@dataclass
class ViralityScore:
    total: float
    novelty: float
    engagement_potential: float
    debate_potential: float
    repostability: float
    emotional_impact: float
    clarity: float
    duration_fit: float
    topic_fit: float
    publish: bool
    reason: str
    theme: str
    score_version: str = "v2"
    source_scores: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EditorialPackage:
    hook: str
    context: str
    tension: str
    remate: str
    cta: str
    caption: str
    overlay: str
    publish: bool
    reason: str
    angle: str
    style: str
    prompt_used: str = ""
    input_payload: Dict[str, Any] = field(default_factory=dict)
    feedback_summary: str = ""
    hook_type: str = ""
    tone: str = ""
    pattern_signature: str = ""
    anti_fatigue_notes: List[str] = field(default_factory=list)
    raw_response: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FormattedPackage:
    content_key: str
    post_type: str
    caption: str
    thumbnail_path: str = ""
    assets: List[Asset] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["assets"] = [asset.as_dict() for asset in self.assets]
        return payload


@dataclass
class ScheduleDecision:
    scheduled_for: str
    slot_label: str
    priority_rank: int
    reason: str
    slot_bucket: str = ""
    constraints: List[str] = field(default_factory=list)
    preferred_slot: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PublicationRecord:
    platform: str
    status: str
    platform_media_id: str = ""
    platform_post_id: str = ""
    container_id: str = ""
    permalink: str = ""
    caption: str = ""
    post_type: str = ""
    scheduled_for: str = ""
    published_at: str = ""
    error_message: str = ""
    mode: str = "live"
    dry_run: bool = False
    payload: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)
