from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Tuple
from urllib.parse import urlparse

from dotenv import load_dotenv

from storage.config_loader import load_yaml_config


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_int_tuple(name: str, default: Tuple[int, ...]) -> Tuple[int, ...]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    values = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            values.append(int(part))
        except ValueError:
            continue
    return tuple(values) or default


def _get_str_tuple(name: str, default: Tuple[str, ...]) -> Tuple[str, ...]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    values = tuple(part.strip() for part in raw.split(",") if part.strip())
    return values or default


def _normalize_x_source(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        path = (parsed.path or "").strip("/")
        if path:
            raw = path
    raw = raw.replace("x.com/", "").replace("twitter.com/", "").strip("/")
    if "/" in raw:
        raw = raw.split("/", 1)[0]
    return raw.lstrip("@").strip()


def _configured_x_sources(sources_config: dict) -> Tuple[str, ...]:
    sources = sources_config.get("sources") if isinstance(sources_config, dict) else None
    if not isinstance(sources, list):
        return ()
    for item in sources:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").strip().lower() != "x":
            continue
        raw_handles = item.get("handles") or item.get("accounts") or item.get("urls")
        if not isinstance(raw_handles, list):
            return ()
        values = []
        seen = set()
        for raw_handle in raw_handles:
            normalized = _normalize_x_source(str(raw_handle or ""))
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            values.append(normalized)
        return tuple(values)
    return ()


@dataclass(frozen=True)
class PipelineSettings:
    base_dir: Path
    data_dir: Path
    sqlite_path: Path
    timezone: str
    schedule_slots: Tuple[str, ...]
    score_threshold: float
    score_keep_floor: float
    comment_reply_emoji: str
    comment_min_age_minutes: int
    comment_max_age_minutes: int
    analytics_delay_minutes: int
    analytics_lookback_hours: int
    analytics_checkpoint_hours: Tuple[int, ...]
    bucket_elite_percentile: float
    bucket_high_percentile: float
    bucket_medium_percentile: float
    bucket_low_percentile: float
    slot_high_score_min: float
    slot_medium_score_min: float
    schedule_videos_per_slot: int
    schedule_posts_per_slot: int
    publish_default_max_posts: int
    publish_max_per_source_per_block: int
    publish_slot_window_minutes: int
    publish_max_content_age_hours: int
    publish_require_same_local_day: bool
    scrape_default_max_items_per_source: int
    x_default_items_per_handle: int
    x_require_same_local_day: bool
    anti_fatigue_lookback_limit: int
    score_validation_deviation_threshold: float
    source_ranking_lookback_days: int
    editorial_master_prompt_path: Path | None
    openai_api_key: str
    openai_model: str
    openai_base_url: str
    openai_temperature: float
    openai_max_output_tokens: int
    ig_graph_version: str
    ig_access_token: str
    ig_user_id: str
    fb_access_token: str
    fb_page_id: str
    x_sources: Tuple[str, ...]
    x_session_storage_state: Path
    x_user_data_dir: Path
    x_headless: bool
    x_max_scrolls: int
    x_scroll_pause_seconds: float
    x_capture_debug_dir: Path
    formatted_dir: Path
    formatted_video_dir: Path
    formatted_image_dir: Path
    daily_report_dir: Path
    output_dir: Path
    backup_dir: Path
    ffmpeg_path: str
    ffprobe_path: str
    x_mode: str
    enable_instagram: bool
    enable_facebook: bool
    enable_comment_engagement: bool
    enable_auto_tuning: bool
    live_publish_enabled: bool
    safe_mode_default: bool
    meta_permissions: Tuple[str, ...]
    sources_config_path: Path
    thresholds_config_path: Path
    editorial_policy_path: Path
    sources_config: dict
    thresholds_config: dict
    editorial_policy: dict
    webapp_holasalta_path: Path | None
    debug: bool


@lru_cache(maxsize=1)
def get_settings() -> PipelineSettings:
    data_dir = BASE_DIR / "data"
    config_dir = BASE_DIR / "config"
    sources_config_path = Path(os.getenv("DUO_SOURCES_CONFIG", str(config_dir / "sources.yaml")))
    thresholds_config_path = Path(os.getenv("DUO_THRESHOLDS_CONFIG", str(config_dir / "thresholds.yaml")))
    editorial_policy_path = Path(os.getenv("DUO_EDITORIAL_POLICY_PATH", str(config_dir / "editorial_policy.yaml")))
    sources_config = load_yaml_config(sources_config_path)
    thresholds_config = load_yaml_config(thresholds_config_path)
    editorial_policy = load_yaml_config(editorial_policy_path)
    configured_slots = thresholds_config.get("scheduler_slots") if isinstance(thresholds_config, dict) else None
    default_slots = ",".join(configured_slots) if isinstance(configured_slots, list) else "09:00,12:00,15:00,18:00,21:00"
    schedule_slots = tuple(
        slot.strip()
        for slot in os.getenv(
            "DUO_SCHEDULE_SLOTS",
            default_slots,
        ).split(",")
        if slot.strip()
    )
    quotas = thresholds_config.get("quotas") if isinstance(thresholds_config, dict) else {}
    quotas = quotas if isinstance(quotas, dict) else {}
    schedule_videos_per_slot = _get_int(
        "DUO_SCHEDULE_VIDEOS_PER_SLOT",
        int(quotas.get("videos_per_slot") or quotas.get("reels_per_slot") or 5),
    )
    schedule_posts_per_slot = _get_int(
        "DUO_SCHEDULE_POSTS_PER_SLOT",
        int(quotas.get("posts_per_slot") or 10),
    )
    schedule_block_size = max(1, max(0, schedule_videos_per_slot) + max(0, schedule_posts_per_slot))
    editorial_prompt = os.getenv("DUO_EDITORIAL_MASTER_PROMPT_PATH", "").strip()
    configured_x_sources = _configured_x_sources(sources_config)
    env_x_sources = os.getenv("X_SOURCES", "").strip()
    raw_x_sources = (
        env_x_sources.split(",")
        if env_x_sources
        else configured_x_sources
        or (
            "UnPocoTende",
            "Trumperizar",
            "TTendenciaX",
            "therealbuni",
            "Tv_Libertaria",
            "porqueTTarg",
        )
    )
    x_sources = tuple(
        normalized
        for source in raw_x_sources
        for normalized in [_normalize_x_source(source)]
        if normalized
    )
    return PipelineSettings(
        base_dir=BASE_DIR,
        data_dir=data_dir,
        sqlite_path=Path(os.getenv("SQLITE_PATH") or os.getenv("DUO_DB_PATH", str(data_dir / "duo_pipeline.sqlite3"))),
        timezone=os.getenv("DUO_TIMEZONE", "America/Buenos_Aires"),
        schedule_slots=schedule_slots,
        score_threshold=_get_float("DUO_SCORE_THRESHOLD", float(thresholds_config.get("publish_threshold") or 62.0)),
        score_keep_floor=_get_float("DUO_SCORE_KEEP_FLOOR", 45.0),
        comment_reply_emoji=os.getenv("DUO_COMMENT_REPLY_EMOJI", "🔥").strip() or "🔥",
        comment_min_age_minutes=_get_int("DUO_COMMENT_MIN_AGE_MINUTES", 10),
        comment_max_age_minutes=_get_int("DUO_COMMENT_MAX_AGE_MINUTES", 20),
        analytics_delay_minutes=_get_int("DUO_ANALYTICS_DELAY_MINUTES", 20),
        analytics_lookback_hours=_get_int("DUO_ANALYTICS_LOOKBACK_HOURS", 72),
        analytics_checkpoint_hours=_get_int_tuple("DUO_ANALYTICS_CHECKPOINT_HOURS", (1, 6, 24)),
        bucket_elite_percentile=_get_float("DUO_BUCKET_ELITE_PERCENTILE", 0.90),
        bucket_high_percentile=_get_float("DUO_BUCKET_HIGH_PERCENTILE", 0.70),
        bucket_medium_percentile=_get_float("DUO_BUCKET_MEDIUM_PERCENTILE", 0.30),
        bucket_low_percentile=_get_float("DUO_BUCKET_LOW_PERCENTILE", 0.20),
        slot_high_score_min=_get_float("DUO_SLOT_HIGH_SCORE_MIN", 75.0),
        slot_medium_score_min=_get_float("DUO_SLOT_MEDIUM_SCORE_MIN", 62.0),
        schedule_videos_per_slot=max(0, schedule_videos_per_slot),
        schedule_posts_per_slot=max(0, schedule_posts_per_slot),
        publish_default_max_posts=_get_int("DUO_PUBLISH_DEFAULT_MAX_POSTS", schedule_block_size),
        publish_max_per_source_per_block=_get_int("DUO_PUBLISH_MAX_PER_SOURCE_PER_BLOCK", 2),
        publish_slot_window_minutes=_get_int(
            "DUO_PUBLISH_SLOT_WINDOW_MINUTES",
            int(quotas.get("publish_slot_window_minutes") or 45),
        ),
        publish_max_content_age_hours=_get_int(
            "DUO_PUBLISH_MAX_CONTENT_AGE_HOURS",
            int(quotas.get("publish_max_content_age_hours") or 24),
        ),
        publish_require_same_local_day=_get_bool("DUO_PUBLISH_REQUIRE_SAME_LOCAL_DAY", True),
        scrape_default_max_items_per_source=_get_int("DUO_SCRAPE_DEFAULT_MAX_ITEMS_PER_SOURCE", 10),
        x_default_items_per_handle=_get_int("DUO_X_DEFAULT_ITEMS_PER_HANDLE", 8),
        x_require_same_local_day=_get_bool("DUO_X_REQUIRE_SAME_LOCAL_DAY", False),
        anti_fatigue_lookback_limit=_get_int("DUO_ANTI_FATIGUE_LOOKBACK_LIMIT", 15),
        score_validation_deviation_threshold=_get_float(
            "DUO_SCORE_VALIDATION_DEVIATION_THRESHOLD",
            15.0,
        ),
        source_ranking_lookback_days=_get_int("DUO_SOURCE_RANKING_LOOKBACK_DAYS", 30),
        editorial_master_prompt_path=Path(editorial_prompt) if editorial_prompt else None,
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip(),
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/responses").strip(),
        openai_temperature=_get_float("OPENAI_TEMPERATURE", 0.7),
        openai_max_output_tokens=_get_int("OPENAI_MAX_OUTPUT_TOKENS", 900),
        ig_graph_version=os.getenv("IG_GRAPH_VERSION", "v25.0").strip(),
        ig_access_token=(os.getenv("META_ACCESS_TOKEN") or os.getenv("IG_ACCESS_TOKEN", "")).strip(),
        ig_user_id=(os.getenv("META_IG_USER_ID") or os.getenv("IG_USER_ID", "")).strip(),
        fb_access_token=(os.getenv("META_ACCESS_TOKEN") or os.getenv("FB_ACCESS_TOKEN", "")).strip(),
        fb_page_id=(os.getenv("META_PAGE_ID") or os.getenv("FB_PAGE_ID", "")).strip(),
        x_sources=x_sources,
        x_session_storage_state=Path(
            os.getenv("X_SESSION_STORAGE_STATE", str(data_dir / "x_storage_state.json"))
        ),
        x_user_data_dir=Path(
            os.getenv("X_USER_DATA_DIR", str(data_dir / "x_playwright_profile"))
        ),
        x_headless=_get_bool("X_HEADLESS", True),
        x_max_scrolls=_get_int("X_MAX_SCROLLS", 10),
        x_scroll_pause_seconds=_get_float("X_SCROLL_PAUSE_SECONDS", 2.5),
        x_capture_debug_dir=Path(
            os.getenv("X_CAPTURE_DEBUG_DIR", str(data_dir / "x_debug_payloads"))
        ),
        formatted_dir=Path(os.getenv("DUO_FORMATTED_DIR", str(data_dir / "pipeline_formatted"))),
        formatted_video_dir=Path(
            os.getenv("DUO_FORMATTED_VIDEO_DIR", str(data_dir / "pipeline_formatted" / "reels"))
        ),
        formatted_image_dir=Path(
            os.getenv("DUO_FORMATTED_IMAGE_DIR", str(data_dir / "pipeline_formatted" / "images"))
        ),
        daily_report_dir=Path(os.getenv("DUO_DAILY_REPORT_DIR", str(data_dir / "reports"))),
        output_dir=Path(os.getenv("OUTPUT_DIR", str(data_dir / "pipeline_formatted"))),
        backup_dir=Path(os.getenv("DUO_SQLITE_BACKUP_DIR", str(BASE_DIR / "storage" / "backups"))),
        ffmpeg_path=os.getenv("FFMPEG_PATH") or os.getenv("FFMPEG_BIN", "ffmpeg"),
        ffprobe_path=os.getenv("FFPROBE_PATH") or os.getenv("FFMPEG_PROBE_BIN", "ffprobe"),
        x_mode=os.getenv("X_MODE", "manual").strip().lower() or "manual",
        enable_instagram=_get_bool("ENABLE_INSTAGRAM", True),
        enable_facebook=_get_bool("ENABLE_FACEBOOK", True),
        enable_comment_engagement=_get_bool("ENABLE_COMMENT_ENGAGEMENT", False),
        enable_auto_tuning=_get_bool("ENABLE_AUTO_TUNING", False),
        live_publish_enabled=_get_bool("DUO_LIVE_PUBLISH_ENABLED", False),
        safe_mode_default=_get_bool("DUO_SAFE_MODE_DEFAULT", True),
        meta_permissions=_get_str_tuple(
            "META_PERMISSIONS",
            (
                "pages_show_list",
                "business_management",
                "instagram_basic",
                "instagram_content_publish",
                "pages_read_engagement",
                "pages_read_user_content",
                "pages_manage_posts",
            ),
        ),
        sources_config_path=sources_config_path,
        thresholds_config_path=thresholds_config_path,
        editorial_policy_path=editorial_policy_path,
        sources_config=sources_config,
        thresholds_config=thresholds_config,
        editorial_policy=editorial_policy,
        webapp_holasalta_path=Path(os.getenv("WEBAPP_HOLASALTA_PATH")) if os.getenv("WEBAPP_HOLASALTA_PATH") else None,
        debug=_get_bool("DUO_DEBUG", False),
    )
