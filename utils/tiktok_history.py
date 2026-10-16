"""TikTok publish history and dedup helpers."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set


def compute_file_sha1(file_path: str, chunk_size: int = 1024 * 1024) -> str:
    hasher = hashlib.sha1()
    path = Path(file_path)
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def build_tiktok_key(item: Dict[str, Any], video_path: str) -> str:
    if isinstance(item, dict):
        ig_key = str(item.get("ig_key") or "").strip()
        if ig_key:
            return ig_key
    return compute_file_sha1(video_path)


def load_tiktok_history(path: str | Path) -> List[Dict[str, Any]]:
    history_path = Path(path)
    if not history_path.exists():
        return []
    try:
        payload = json.loads(history_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def history_keys(history: Iterable[Dict[str, Any]]) -> Set[str]:
    keys: Set[str] = set()
    for row in history:
        key = str(row.get("key") or "").strip()
        if key:
            keys.add(key)
    return keys


def already_published(path: str | Path, key: str) -> bool:
    history = load_tiktok_history(path)
    return key in history_keys(history)


def append_tiktok_history(
    path: str | Path,
    *,
    key: str,
    video: str,
    caption: str,
    post_url: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    history_path = Path(path)
    records = load_tiktok_history(history_path)
    current_keys = history_keys(records)
    if key in current_keys:
        for record in records:
            if str(record.get("key") or "").strip() == key:
                return record

    item: Dict[str, Any] = {
        "key": key,
        "video": video,
        "caption": caption,
        "post_url": post_url or "",
        "published_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        item.update(extra)

    records.append(item)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return item
