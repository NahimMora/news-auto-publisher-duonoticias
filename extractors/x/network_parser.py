from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


def parse_twitter_timestamp(value: str) -> int:
    if not value:
        return 0
    try:
        return int(datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y").timestamp())
    except Exception:
        return 0


def extract_video_tweets_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    _collect_tweet_candidates(payload, candidates)
    results: List[Dict[str, Any]] = []
    seen = set()
    for candidate in candidates:
        parsed = parse_tweet_result(candidate)
        tweet_id = parsed.get("tweet_id")
        if not tweet_id or tweet_id in seen:
            continue
        seen.add(tweet_id)
        results.append(parsed)
    return results


def parse_tweet_result(tweet: Dict[str, Any]) -> Dict[str, Any]:
    legacy = tweet.get("legacy") or {}
    core = tweet.get("core") or {}
    user_result = ((core.get("user_results") or {}).get("result") or {})
    user_legacy = user_result.get("legacy") or {}
    user_core = user_result.get("core") or {}
    media_items = ((legacy.get("extended_entities") or {}).get("media") or [])

    videos = []
    duration_seconds = 0.0
    for media in media_items:
        media_type = media.get("type")
        if media_type not in {"video", "animated_gif"}:
            continue
        variant = _best_video_variant(media)
        if not variant:
            continue
        duration_seconds = max(duration_seconds, float((media.get("video_info") or {}).get("duration_millis") or 0) / 1000.0)
        videos.append(
            {
                "type": media_type,
                "media_key": media.get("media_key"),
                "url": variant,
                "thumbnail_url": media.get("media_url_https") or media.get("media_url"),
            }
        )

    views = _safe_float(((tweet.get("views") or {}).get("count")) or legacy.get("view_count") or 0)
    return {
        "tweet_id": str(tweet.get("rest_id") or ""),
        "tweet_url": f"https://x.com/i/status/{tweet.get('rest_id')}",
        "author": user_legacy.get("name") or user_core.get("name") or "",
        "handle": user_legacy.get("screen_name") or user_core.get("screen_name") or "",
        "original_text": legacy.get("full_text") or legacy.get("text") or "",
        "timestamp": parse_twitter_timestamp(legacy.get("created_at") or ""),
        "duration_seconds": duration_seconds,
        "visible_metrics": {
            "likes": _safe_float(legacy.get("favorite_count")),
            "comments": _safe_float(legacy.get("reply_count")),
            "shares": _safe_float(legacy.get("retweet_count")),
            "quotes": _safe_float(legacy.get("quote_count")),
            "bookmarks": _safe_float(legacy.get("bookmark_count")),
            "views": views,
        },
        "media": videos,
        "raw_payload": tweet,
    }


def _collect_tweet_candidates(node: Any, sink: List[Dict[str, Any]]) -> None:
    if isinstance(node, dict):
        if node.get("__typename") == "Tweet" and node.get("rest_id") and node.get("legacy"):
            sink.append(node)
        tweet_results = node.get("tweet_results")
        if isinstance(tweet_results, dict):
            result = tweet_results.get("result")
            if isinstance(result, dict):
                _collect_tweet_candidates(result, sink)
        for value in node.values():
            _collect_tweet_candidates(value, sink)
        return
    if isinstance(node, list):
        for item in node:
            _collect_tweet_candidates(item, sink)


def _best_video_variant(media: Dict[str, Any]) -> Optional[str]:
    variants = ((media.get("video_info") or {}).get("variants") or [])
    candidates = [
        item
        for item in variants
        if item.get("content_type") == "video/mp4" and item.get("url")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.get("bitrate") or 0, reverse=True)
    return str(candidates[0].get("url") or "")


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0
