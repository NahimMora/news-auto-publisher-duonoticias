import argparse
import json
import logging
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

import httpx
import re

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads" / "x"
PROCESSED_PATH = BASE_DIR / "processed_videos.json"
COOKIE_DEFAULT = Path("scrapping/cookies.txt")

def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _load_processed() -> set[str]:
    if not PROCESSED_PATH.exists():
        return set()
    try:
        data = json.loads(PROCESSED_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {str(x) for x in data}
    except Exception:
        return set()
    return set()


def _save_processed(processed: set[str]) -> None:
    PROCESSED_PATH.write_text(
        json.dumps(sorted(processed), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _run_yt_dlp(args: List[str], retry: int = 1) -> subprocess.CompletedProcess:
    last_exc: Optional[Exception] = None
    timeout = int(os.getenv("X_YTDLP_TIMEOUT_SECONDS", "45"))
    for attempt in range(retry + 1):
        try:
            return subprocess.run(
                args,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            last_exc = exc
            if attempt < retry:
                time.sleep(1)
                continue
            return subprocess.CompletedProcess(args, 124, "", f"yt-dlp timed out after {timeout}s")
        except Exception as exc:
            last_exc = exc
            if attempt < retry:
                time.sleep(1)
                continue
            raise exc from last_exc
    raise RuntimeError("yt-dlp invocation failed")


def _extract_tweet_info(tweet_url: str, cookies: Optional[str], retry: int = 1) -> Dict[str, Any]:
    cmd = ["yt-dlp", "--dump-json", "--socket-timeout", os.getenv("X_YTDLP_SOCKET_TIMEOUT", "15"), tweet_url]
    if cookies:
        cmd.extend(["--cookies", cookies])
    proc = _run_yt_dlp(cmd, retry=retry)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        expected = (
            "No video could be found" in stderr
            or "Suspended" in stderr
            or "Unsupported URL" in stderr
            or "This post is unavailable" in stderr
        )
        log = logging.info if expected else logging.warning
        log("yt-dlp info failed for %s (code %s)", tweet_url, proc.returncode)
        if stderr:
            logging.info("yt-dlp stderr: %s", stderr.splitlines()[-1])
        return {}
    stdout = (proc.stdout or "").strip()
    if not stdout:
        return {}
    try:
        return json.loads(stdout)
    except Exception:
        return {}


def _is_recent(item: Dict[str, Any], max_age_seconds: int) -> bool:
    timestamp = item.get("timestamp")
    if not isinstance(timestamp, (int, float)):
        return False
    now = int(time.time())
    return (now - int(timestamp)) <= max_age_seconds


def _is_valid_video_item(item: Dict[str, Any], max_age_seconds: int) -> bool:
    if item.get("_type") == "url":
        return False
    if not item.get("duration"):
        return False
    if not item.get("timestamp"):
        return False
    if not _is_recent(item, max_age_seconds):
        return False
    return True


def _normalize_inputs(inputs: List[str]) -> List[str]:
    urls: List[str] = []
    for entry in inputs:
        entry = entry.strip()
        if not entry:
            continue
        if entry.startswith("http://") or entry.startswith("https://"):
            url = entry.replace("x.com/", "twitter.com/")
            urls.append(url)
        else:
            handle = entry.lstrip("@")
            urls.append(f"https://twitter.com/{handle}")
    return urls


def _load_cookie_jar(cookies_path: Optional[str]) -> tuple[httpx.Cookies, Optional[str]]:
    jar = httpx.Cookies()
    ct0 = None
    if not cookies_path:
        return jar, ct0
    path = Path(cookies_path)
    if not path.exists():
        return jar, ct0
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _, cpath, _, _, name, value = parts[:7]
        jar.set(name, value, domain=domain, path=cpath)
        if domain.endswith("twitter.com"):
            jar.set(name, value, domain=domain.replace("twitter.com", "x.com"), path=cpath)
        if name == "ct0":
            ct0 = value
    return jar, ct0


def _parse_twitter_date(value: str) -> Optional[int]:
    try:
        dt = datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")
        return int(dt.timestamp())
    except Exception:
        return None


def _extract_query_id(js_text: str, operation_name: str) -> Optional[str]:
    pattern = re.compile(
        rf'queryId:"([^"]+)",operationName:"{re.escape(operation_name)}"'
    )
    match = pattern.search(js_text)
    if match:
        return match.group(1)
    return None


def _get_query_id(operation_name: str, cookies_path: Optional[str]) -> Optional[str]:
    headers = {"User-Agent": "Mozilla/5.0"}
    cookies, _ = _load_cookie_jar(cookies_path)
    try:
        resp = httpx.get("https://x.com", headers=headers, cookies=cookies, timeout=20.0)
    except Exception:
        return None
    if resp.status_code != 200 or not resp.text:
        return None
    match = re.search(r"https://abs\.twimg\.com/responsive-web/client-web/main\.[^\"']+\.js", resp.text)
    if not match:
        return None
    js_url = match.group(0)
    try:
        js_resp = httpx.get(js_url, headers=headers, timeout=20.0)
    except Exception:
        return None
    if js_resp.status_code != 200 or not js_resp.text:
        return None
    return _extract_query_id(js_resp.text, operation_name)


def _graphql_search_timeline(
    username: str,
    max_items: int,
    cookies_path: Optional[str],
    max_age_seconds: int,
) -> List[str]:
    cookies, ct0 = _load_cookie_jar(cookies_path)
    bearer_token = os.getenv("X_BEARER_TOKEN", "").strip()
    if not ct0 or not bearer_token:
        return []

    query_id = _get_query_id("SearchTimeline", cookies_path)
    if not query_id:
        return []

    headers = {
        "User-Agent": "Mozilla/5.0",
        "authorization": f"Bearer {bearer_token}",
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "en",
        "x-csrf-token": ct0,
    }

    features = {
        "rweb_lists_timeline_redesign_enabled": False,
        "blue_business_profile_image_shape_enabled": False,
        "responsive_web_graphql_exclude_directive_enabled": True,
        "verified_phone_label_enabled": False,
        "creator_subscriptions_tweet_preview_api_enabled": False,
        "responsive_web_graphql_timeline_navigation_enabled": True,
        "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
        "tweetypie_unmention_optimization_enabled": True,
        "vibe_api_enabled": True,
        "responsive_web_edit_tweet_api_enabled": True,
        "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
        "view_counts_everywhere_api_enabled": True,
        "longform_notetweets_consumption_enabled": True,
        "tweet_awards_web_tipping_enabled": False,
        "freedom_of_speech_not_reach_fetch_enabled": False,
        "standardized_nudges_misinfo": True,
        "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": False,
        "interactive_text_enabled": True,
        "responsive_web_text_conversations_enabled": False,
        "longform_notetweets_rich_text_read_enabled": False,
        "longform_notetweets_inline_media_enabled": False,
        "responsive_web_enhance_cards_enabled": False,
        "responsive_web_twitter_blue_verified_badge_is_enabled": True,
        "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
        "post_ctas_fetch_enabled": False,
        "responsive_web_grok_community_note_auto_translation_is_enabled": False,
        "profile_label_improvements_pcf_label_in_post_enabled": False,
        "responsive_web_grok_analyze_post_followups_enabled": False,
        "responsive_web_grok_analysis_button_from_backend": False,
        "c9s_tweet_anatomy_moderator_badge_enabled": False,
        "creator_subscriptions_quote_tweet_preview_enabled": False,
        "articles_preview_enabled": False,
        "responsive_web_grok_share_attachment_enabled": False,
        "responsive_web_grok_show_grok_translated_post": False,
        "communities_web_enable_tweet_community_results_fetch": False,
        "responsive_web_grok_imagine_annotation_enabled": False,
        "premium_content_api_read_enabled": False,
        "responsive_web_grok_annotations_enabled": False,
        "responsive_web_twitter_article_tweet_consumption_enabled": False,
        "responsive_web_profile_redirect_enabled": False,
        "responsive_web_grok_image_annotation_enabled": False,
        "responsive_web_jetfuel_frame": False,
        "rweb_tipjar_consumption_enabled": False,
        "rweb_video_screen_enabled": False,
    }

    now_ts = int(time.time())
    next_cursor: Optional[str] = None
    tweet_urls: List[str] = []

    while len(tweet_urls) < max_items:
        variables = {
            "rawQuery": f"from:{username} filter:videos",
            "count": 20,
            "product": "Latest",
            "withDownvotePerspective": False,
            "withReactionsMetadata": False,
            "withReactionsPerspective": False,
        }
        if next_cursor:
            variables["cursor"] = next_cursor

        params = {
            "variables": json.dumps(variables, separators=(",", ":")),
            "features": json.dumps(features, separators=(",", ":")),
        }
        url = f"https://x.com/i/api/graphql/{query_id}/SearchTimeline"
        try:
            resp = httpx.post(url, headers=headers, cookies=cookies, json={"variables": variables, "features": features}, timeout=20.0)
        except Exception:
            break
        if resp.status_code != 200:
            logging.warning("SearchTimeline status %s", resp.status_code)
            break
        data = resp.json()
        instructions = (
            data.get("data", {})
            .get("search_by_raw_query", {})
            .get("search_timeline", {})
            .get("timeline", {})
            .get("instructions", [])
        )
        if not instructions:
            logging.warning("SearchTimeline sin instrucciones para %s", username)
            break
        entries: List[Dict[str, Any]] = []
        next_cursor = None
        for inst in instructions:
            entries.extend(inst.get("entries") or [])
        for entry in entries:
            entry_id = entry.get("entryId") or ""
            content = entry.get("content") or {}
            if entry_id.startswith("cursor-bottom"):
                next_cursor = (content.get("value") or content.get("cursorType") or None)
                continue
            item = content.get("itemContent", {})
            tweet_result = item.get("tweet_results", {}).get("result", {})
            if not tweet_result or tweet_result.get("__typename") != "Tweet":
                continue
            legacy = tweet_result.get("legacy") or {}
            tweet_id = tweet_result.get("rest_id") or ""
            created_at = legacy.get("created_at") or ""
            ts = _parse_twitter_date(created_at) or 0
            if ts and (now_ts - ts) > max_age_seconds:
                return tweet_urls
            media = (legacy.get("extended_entities") or {}).get("media") or []
            has_video = any(m.get("type") in ("video", "animated_gif") for m in media)
            if not (tweet_id and has_video and ts):
                continue
            tweet_urls.append(f"https://twitter.com/{username}/status/{tweet_id}")
            if len(tweet_urls) >= max_items:
                return tweet_urls
        if not next_cursor:
            break

    return tweet_urls


def _fetch_recent_tweet_urls(
    username: str,
    max_items: int = 200,
    cookies_path: Optional[str] = None,
    max_age_seconds: int = 72 * 3600,
) -> List[str]:
    cache_path = BASE_DIR / f"cache_{username}.json"

    def filter_recent(items: List[str]) -> List[str]:
        recent: List[str] = []
        seen = set()
        for item in items:
            url = str(item or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            if not _is_recent_tweet_url(url, max_age_seconds=max_age_seconds):
                continue
            recent.append(url)
            if len(recent) >= max_items:
                break
        return recent

    def load_cache() -> List[str]:
        if not cache_path.exists():
            return []
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if isinstance(cached, list):
            return filter_recent([str(x) for x in cached])
        return []

    def save_cache(items: List[str]) -> None:
        try:
            cache_path.write_text(json.dumps(filter_recent(items), ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    graphql_urls = _graphql_search_timeline(
        username=username,
        max_items=max_items,
        cookies_path=cookies_path,
        max_age_seconds=max_age_seconds,
    )
    if graphql_urls:
        filtered = filter_recent(graphql_urls)
        save_cache(filtered)
        return filtered
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ]
    url = f"https://cdn.syndication.twimg.com/srv/timeline-profile/screen-name/{username}?dnt=false&lang=en"

    resp = None
    syndication_retries = max(1, int(os.getenv("X_SYNDICATION_RETRIES", "2")))
    for attempt in range(syndication_retries):
        headers = {"User-Agent": user_agents[attempt % len(user_agents)]}
        for candidate in (url, f"https://r.jina.ai/http://{url}"):
            try:
                resp = httpx.get(candidate, headers=headers, timeout=20.0)
            except Exception:
                resp = None
            if resp is not None and resp.status_code == 200 and resp.text:
                break
            if resp is not None and resp.status_code == 429:
                break
        if resp is not None and resp.status_code == 200 and resp.text:
            break
        if resp is not None and resp.status_code == 429:
            time.sleep(2 ** attempt)
            continue
        time.sleep(1.5 + attempt)

    text = resp.text if resp is not None and resp.status_code == 200 and resp.text else ""
    if resp is not None and resp.status_code == 429:
        logging.warning("Syndication rate-limited (429) for %s. Usando fallback/cache.", username)
    if not text:
        cache_bust = int(time.time())
        for fallback in (
            f"https://r.jina.ai/http://x.com/{username}/media?ts={cache_bust}",
            f"https://r.jina.ai/http://x.com/{username}?ts={cache_bust}",
            f"https://r.jina.ai/http://twitter.com/{username}/media?ts={cache_bust}",
            f"https://r.jina.ai/http://twitter.com/{username}?ts={cache_bust}",
        ):
            try:
                fb = httpx.get(fallback, headers={"User-Agent": user_agents[0]}, timeout=20.0)
            except Exception:
                fb = None
            if fb is not None and fb.status_code == 200 and fb.text:
                text = fb.text
                break

    if not text:
        cache_bust = int(time.time())
        search_url = (
            f"https://r.jina.ai/http://x.com/search?q=from%3A{username}%20filter%3Avideos&f=live&ts={cache_bust}"
        )
        try:
            search_resp = httpx.get(search_url, headers={"User-Agent": user_agents[0]}, timeout=20.0)
        except Exception:
            search_resp = None
        if search_resp is not None and search_resp.status_code == 200 and search_resp.text:
            text = search_resp.text

    if not text:
        logging.warning("No se pudo obtener timeline para %s. Usando cache si existe.", username)
        return load_cache()

    ids = re.findall(r"/status/(\d+)", text)
    unique_ids = sorted({int(t) for t in ids}, reverse=True)
    tweet_urls: List[str] = []
    for tid in unique_ids:
        tweet_urls.append(f"https://twitter.com/{username}/status/{tid}")
        if len(tweet_urls) >= max_items:
            break
    if tweet_urls:
        filtered = filter_recent(tweet_urls)
        if filtered:
            save_cache(filtered)
            return filtered
    cached = load_cache()
    if cached:
        logging.warning("No se detectaron links nuevos para %s. Usando cache.", username)
    return cached


def _tweet_id_from_url(url: str) -> Optional[str]:
    match = re.search(r"/status/(\d+)", url)
    return match.group(1) if match else None


def _tweet_timestamp_from_id(tweet_id: str) -> Optional[int]:
    try:
        tid = int(tweet_id)
    except Exception:
        return None
    timestamp_ms = (tid >> 22) + 1288834974657
    return int(timestamp_ms / 1000)


def _is_recent_tweet_url(url: str, *, max_age_seconds: int) -> bool:
    tweet_id = _tweet_id_from_url(url)
    tweet_ts = _tweet_timestamp_from_id(tweet_id) if tweet_id else None
    if not tweet_ts:
        return False
    now_ts = int(time.time())
    age_seconds = now_ts - tweet_ts
    return 0 <= age_seconds <= max_age_seconds


def _download_video(tweet_url: str, tweet_id: str, cookies: Optional[str], retry: int = 1) -> Optional[Path]:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    output_template = str(DOWNLOAD_DIR / f"{tweet_id}.%(ext)s")
    cmd = [
        "yt-dlp",
        "-f",
        "bv*+ba/b",
        "--merge-output-format",
        "mp4",
        "-o",
        output_template,
        tweet_url,
    ]
    if cookies:
        cmd.extend(["--cookies", cookies])

    proc = _run_yt_dlp(cmd, retry=retry)
    if proc.returncode != 0:
        logging.warning("yt-dlp download failed for %s (code %s)", tweet_url, proc.returncode)
        return None

    candidate = DOWNLOAD_DIR / f"{tweet_id}.mp4"
    if candidate.exists():
        return candidate
    return None


def extract_recent_videos(
    inputs: List[str],
    max_videos: int = 15,
    max_age_hours: int = 72,
    cookies: Optional[str] = None,
    dry_run: bool = False,
    include_processed: bool = False,
    allow_old_direct_links: bool = False,
) -> List[Dict[str, Any]]:
    max_age_seconds = max_age_hours * 3600
    processed = _load_processed()
    urls = _normalize_inputs(inputs)

    candidates: List[Dict[str, Any]] = []
    direct_tweet_urls = [u for u in urls if re.search(r"/status/\d+", u)]
    for tweet_url in direct_tweet_urls:
        info = _extract_tweet_info(tweet_url, cookies=cookies, retry=1)
        if not info:
            continue
        if allow_old_direct_links:
            if info.get("_type") == "url" or not info.get("duration"):
                continue
        elif not _is_valid_video_item(info, max_age_seconds=max_age_seconds):
            continue
        tweet_id = str(info.get("id") or "").strip()
        if not tweet_id:
            continue
        if not include_processed and tweet_id in processed:
            continue
        candidates.append(info)

    for url in urls:
        if re.search(r"/status/\d+", url):
            continue
        match = re.search(r"twitter\.com/([^/]+)", url)
        username = match.group(1) if match else ""
        if not username:
            continue
        tweet_urls = _fetch_recent_tweet_urls(
            username,
            max_items=max_videos * 50,
            cookies_path=cookies,
            max_age_seconds=max_age_seconds,
        )
        logging.info("Tweets detectados para %s: %s", username, len(tweet_urls))
        if tweet_urls:
            newest_id = _tweet_id_from_url(tweet_urls[0])
            newest_ts = _tweet_timestamp_from_id(newest_id) if newest_id else None
            if newest_ts:
                age_hours = (int(time.time()) - newest_ts) / 3600
                logging.info("Ultimo tweet detectado: %.1f horas", age_hours)
        now_ts = int(time.time())
        for tweet_url in tweet_urls:
            tweet_id_from_url = _tweet_id_from_url(tweet_url)
            if not tweet_id_from_url:
                continue
            tweet_ts = _tweet_timestamp_from_id(tweet_id_from_url)
            if tweet_ts and (now_ts - tweet_ts) > max_age_seconds:
                break
            info = _extract_tweet_info(tweet_url, cookies=cookies, retry=1)
            if not info:
                continue
            if not _is_valid_video_item(info, max_age_seconds=max_age_seconds):
                continue
            tweet_id = str(info.get("id") or "").strip()
            if not tweet_id:
                continue
            if not include_processed and tweet_id in processed:
                continue
            candidates.append(info)

    if not candidates:
        logging.info("No se encontraron videos recientes (<= %s horas).", max_age_hours)
        return []

    candidates.sort(key=lambda x: int(x.get("timestamp", 0)), reverse=True)
    selected = candidates[:max_videos]

    results: List[Dict[str, Any]] = []
    for item in selected:
        tweet_id = str(item.get("id") or "").strip()
        if not tweet_id:
            continue
        tweet_url = item.get("url") or item.get("webpage_url") or f"https://twitter.com/i/status/{tweet_id}"
        author = item.get("uploader") or item.get("uploader_id") or item.get("channel") or ""
        original_text = item.get("description") or item.get("title") or ""
        timestamp = int(item.get("timestamp", 0))

        if dry_run:
            video_path = str(DOWNLOAD_DIR / f"{tweet_id}.mp4")
        else:
            downloaded = _download_video(tweet_url, tweet_id, cookies=cookies, retry=1)
            if not downloaded:
                continue
            video_path = str(downloaded)

        results.append(
            {
                "tweet_id": tweet_id,
                "tweet_url": tweet_url,
                "author": author,
                "original_text": original_text,
                "timestamp": timestamp,
                "video_path": video_path,
                "duration": item.get("duration"),
            }
        )
        if not include_processed:
            processed.add(tweet_id)

    if results and not include_processed:
        _save_processed(processed)
    else:
        logging.info("No se descargaron videos nuevos.")

    return results


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extractor X videos recientes via yt-dlp")
    parser.add_argument("inputs", nargs="+", help="URL de perfil X o username")
    parser.add_argument("--max-videos", type=int, default=15, help="Max videos a descargar")
    parser.add_argument("--max-age-hours", type=int, default=72, help="Max edad en horas")
    parser.add_argument("--cookies", default=None, help="Ruta a cookies.txt")
    parser.add_argument("--dry-run", action="store_true", help="No descarga, solo lista")
    parser.add_argument(
        "--include-processed",
        action="store_true",
        help="Permite reprocesar links ya descargados antes",
    )
    parser.add_argument(
        "--allow-old-direct-links",
        action="store_true",
        help="No descarta links directos por antiguedad",
    )
    return parser.parse_args()


def main() -> None:
    _setup_logging()
    args = _parse_args()
    results = extract_recent_videos(
        inputs=args.inputs,
        max_videos=args.max_videos,
        max_age_hours=args.max_age_hours,
        cookies=args.cookies,
        dry_run=args.dry_run,
        include_processed=args.include_processed,
        allow_old_direct_links=args.allow_old_direct_links,
    )
    logging.info("Total: %s videos", len(results))
    if results:
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        out_path = BASE_DIR / f"results_{stamp}.json"
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        logging.info("Metadata: %s", out_path)


if __name__ == "__main__":
    main()
