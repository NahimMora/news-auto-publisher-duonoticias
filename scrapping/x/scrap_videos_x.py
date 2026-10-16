"""Scrape video tweet URLs and descriptions from X without Selenium."""
import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import snscrape.modules.twitter as sntwitter
import feedparser
from yt_dlp import YoutubeDL
import re

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"


def _best_video_url(info: Dict[str, Any]) -> Optional[str]:
    formats = info.get("formats") or []
    candidates = [
        f
        for f in formats
        if f.get("ext") == "mp4" and f.get("url") and f.get("protocol") in ("https", "http")
    ]
    if not candidates:
        if info.get("url"):
            return info.get("url")
        return None
    # prefer highest resolution
    candidates.sort(key=lambda f: (f.get("height") or 0, f.get("tbr") or 0), reverse=True)
    return candidates[0].get("url")


def _extract_video_url(tweet_url: str, cookies: Optional[str] = None) -> Optional[str]:
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "no_warnings": True,
        "noplaylist": True,
        "extractor_retries": 2,
    }
    if cookies:
        ydl_opts["cookies"] = cookies
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(tweet_url, download=False)
    return _best_video_url(info)


def _load_cookies_from_netscape(path: str) -> httpx.Cookies:
    jar = httpx.Cookies()
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return jar
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _, cookie_path, _, _, name, value = parts[:7]
        jar.set(name, value, domain=domain, path=cookie_path)
    return jar


def _scrape_with_cookie_html(username: str, limit: int, cookies_path: str) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    cookies = _load_cookies_from_netscape(cookies_path)
    headers = {"User-Agent": "Mozilla/5.0"}
    urls = [
        f"https://x.com/{username}",
        f"https://x.com/{username}/media",
        f"https://twitter.com/{username}",
        f"https://twitter.com/{username}/media",
    ]
    tweet_urls: List[str] = []
    with httpx.Client(timeout=20.0, headers=headers, cookies=cookies, follow_redirects=True) as client:
        for url in urls:
            try:
                resp = client.get(url)
            except Exception:
                continue
            if resp.status_code != 200 or not resp.text:
                continue
            ids = re.findall(rf'/{re.escape(username)}/status/(\d+)', resp.text)
            for tid in ids:
                tweet_url = f"https://x.com/{username}/status/{tid}"
                if tweet_url not in tweet_urls:
                    tweet_urls.append(tweet_url)
            if tweet_urls:
                break

    for tweet_url in tweet_urls:
        if len(results) >= limit:
            break
        try:
            video_url = _extract_video_url(tweet_url, cookies=cookies_path)
        except Exception:
            video_url = None
        if not video_url:
            continue
        results.append(
            {
                "tweet_url": tweet_url,
                "video_url": video_url,
                "description": "",
                "created_at": None,
            }
        )
    return results


def _scrape_with_ytdlp_user(username: str, limit: int, cookies: Optional[str] = None) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    seen = set()
    user_urls = [
        f"https://x.com/{username}",
        f"https://x.com/{username}/media",
        f"https://twitter.com/{username}",
        f"https://twitter.com/{username}/media",
    ]
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "noplaylist": False,
    }
    if cookies:
        ydl_opts["cookies"] = cookies
    with YoutubeDL(ydl_opts) as ydl:
        for url in user_urls:
            try:
                info = ydl.extract_info(url, download=False)
            except Exception:
                continue
            entries = info.get("entries") if isinstance(info, dict) else None
            if not entries:
                continue
            for entry in entries:
                if len(results) >= limit:
                    break
                tweet_url = entry.get("url") or entry.get("webpage_url")
                if not tweet_url or tweet_url in seen:
                    continue
                seen.add(tweet_url)
                description = (entry.get("title") or "").strip()
                try:
                    video_url = _extract_video_url(tweet_url, cookies=cookies)
                except Exception:
                    video_url = None
                if not video_url:
                    continue
                results.append(
                    {
                        "tweet_url": tweet_url,
                        "video_url": video_url,
                        "description": description,
                        "created_at": None,
                    }
                )
            if results:
                break
    return results


def _scrape_with_snscrape(username: str, limit: int) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    scraper = sntwitter.TwitterUserScraper(username)
    for tweet in scraper.get_items():
        if len(results) >= limit:
            break
        if not tweet.media:
            continue
        has_video = any(getattr(m, "__class__", None).__name__ == "Video" for m in tweet.media)
        if not has_video:
            continue
        tweet_url = tweet.url
        description = (tweet.content or "").strip()
        try:
            video_url = _extract_video_url(tweet_url)
        except Exception:
            video_url = None
        results.append(
            {
                "tweet_url": tweet_url,
                "video_url": video_url,
                "description": description,
                "created_at": tweet.date.isoformat() if tweet.date else None,
            }
        )
    return results


def _scrape_with_nitter(username: str, limit: int, bases: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    instances = bases or [
        "https://nitter.net",
        "https://nitter.it",
        "https://nitter.privacydev.net",
        "https://nitter.fdn.fr",
        "https://nitter.poast.org",
        "https://nitter.1d4.us",
        "https://nitter.rawbit.ch",
        "https://nitter.kavin.rocks",
        "https://nitter.woodland.cafe",
        "https://nitter.hostux.net",
        "https://nitter.unixfox.eu",
        "https://nitter.eu.org",
        "https://nitter.nl",
        "https://xcancel.com",
        "https://fxtwitter.com",
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    client = httpx.Client(timeout=15.0, headers=headers, follow_redirects=True)
    feed = None
    for base in instances:
        for prefix in ("", "https://r.jina.ai/http://"):
            url = f"{prefix}{base}/{username}/rss"
            try:
                resp = client.get(url)
                if resp.status_code == 200 and resp.text:
                    feed = feedparser.parse(resp.text)
                    if feed and feed.entries:
                        break
            except Exception:
                continue
        if feed and feed.entries:
            break
    if not feed or not feed.entries:
        return results

    for entry in feed.entries:
        if len(results) >= limit:
            break
        tweet_url = entry.get("link")
        if not tweet_url:
            continue
        description = (entry.get("title") or "").strip()
        created = entry.get("published") or entry.get("updated")
        try:
            video_url = _extract_video_url(tweet_url)
        except Exception:
            video_url = None
        # only keep items with video URL
        if not video_url:
            continue
        results.append(
            {
                "tweet_url": tweet_url,
                "video_url": video_url,
                "description": description,
                "created_at": created,
            }
        )
    return results


def _get_bearer_token(client: httpx.Client) -> Optional[str]:
    env_token = os.getenv("X_BEARER_TOKEN")
    if env_token:
        return env_token
    sources = ["https://x.com", "https://twitter.com"]
    js_url = None
    for src in sources:
        try:
            resp = client.get(src)
            if resp.status_code != 200:
                continue
            # Find main client JS (new or legacy)
            match = re.search(
                r'https://abs\.twimg\.com/responsive-web/client-web/(main|client-web-legacy)\.[^"]+\.js',
                resp.text,
            )
            if match:
                js_url = match.group(0)
                break
        except Exception:
            continue
    if not js_url:
        return None
    try:
        js = client.get(js_url)
        if js.status_code != 200:
            return None
        token_match = re.search(r'Bearer ([A-Za-z0-9%-]+)', js.text)
        if token_match:
            return token_match.group(1)
    except Exception:
        return None
    return None


def _activate_guest_token(client: httpx.Client, bearer: str) -> Optional[str]:
    try:
        resp = client.post(
            "https://api.twitter.com/1.1/guest/activate.json",
            headers={"Authorization": f"Bearer {bearer}"},
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("guest_token")
    except Exception:
        return None
    return None


def _pick_variant(media: Dict[str, Any]) -> Optional[str]:
    variants = (media.get("video_info") or {}).get("variants") or []
    mp4s = [v for v in variants if v.get("content_type") == "video/mp4" and v.get("url")]
    if not mp4s:
        return None
    mp4s.sort(key=lambda v: v.get("bitrate", 0), reverse=True)
    return mp4s[0].get("url")


def _scrape_with_guest_api(username: str, limit: int, debug: bool = False) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    headers = {"User-Agent": "Mozilla/5.0"}
    with httpx.Client(timeout=20.0, headers=headers, follow_redirects=True) as client:
        bearer = _get_bearer_token(client)
        if not bearer:
            if debug:
                print("[x] bearer token not found")
            return results
        guest = _activate_guest_token(client, bearer)
        if not guest:
            if debug:
                print("[x] guest token activation failed")
            return results

        api_headers = {
            "Authorization": f"Bearer {bearer}",
            "x-guest-token": guest,
        }
        params = {
            "screen_name": username,
            "count": str(max(limit * 2, 20)),
            "tweet_mode": "extended",
            "include_entities": "1",
            "exclude_replies": "false",
            "include_rts": "false",
        }
        resp = client.get(
            "https://api.twitter.com/1.1/statuses/user_timeline.json",
            headers=api_headers,
            params=params,
        )
        if resp.status_code != 200:
            if debug:
                print(f"[x] timeline status={resp.status_code} body={resp.text[:200]}")
            return results
        items = resp.json() if resp.content else []
        for item in items:
            if len(results) >= limit:
                break
            media = None
            extended = item.get("extended_entities") or {}
            for m in extended.get("media", []) or []:
                if m.get("type") in ("video", "animated_gif"):
                    media = m
                    break
            if not media:
                continue
            video_url = _pick_variant(media)
            if not video_url:
                continue
            tweet_id = item.get("id_str") or str(item.get("id"))
            tweet_url = f"https://x.com/{username}/status/{tweet_id}"
            description = (item.get("full_text") or "").strip()
            created = item.get("created_at")
            results.append(
                {
                    "tweet_url": tweet_url,
                    "video_url": video_url,
                    "description": description,
                    "created_at": created,
                }
            )
    return results


def _find_query_id(js_text: str, operation: str) -> Optional[str]:
    direct = re.search(rf'i/api/graphql/([A-Za-z0-9_-]+)/{re.escape(operation)}', js_text)
    if direct:
        return direct.group(1)
    patterns = [
        rf'"queryId":"(?P<id>[^"]+)","operationName":"{re.escape(operation)}"',
        rf'"operationName":"{re.escape(operation)}","queryId":"(?P<id>[^"]+)"',
    ]
    for pat in patterns:
        m = re.search(pat, js_text)
        if m:
            return m.group("id")
    return None


def _scrape_with_authenticated_graphql(
    username: str,
    limit: int,
    cookies_path: str,
    debug: bool = False,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    cookies = _load_cookies_from_netscape(cookies_path)
    headers = {"User-Agent": "Mozilla/5.0"}
    with httpx.Client(timeout=25.0, headers=headers, cookies=cookies, follow_redirects=True) as client:
        bearer = _get_bearer_token(client)
        if not bearer:
            if debug:
                print("[x] bearer token not found (auth graphql)")
            return results
        ct0 = cookies.get("ct0")
        if not ct0:
            if debug:
                print("[x] ct0 cookie not found")
            return results

        # load main JS to find query ids
        home = client.get("https://x.com")
        if home.status_code != 200:
            if debug:
                print(f"[x] home status={home.status_code}")
            return results
        match = re.search(
            r'https://abs\.twimg\.com/responsive-web/client-web/(main|client-web-legacy)\.[^"]+\.js',
            home.text,
        )
        if not match:
            if debug:
                print("[x] main js not found")
            return results
        js = client.get(match.group(0))
        if js.status_code != 200:
            if debug:
                print("[x] main js download failed")
            return results

        user_by_name_qid = _find_query_id(js.text, "UserByScreenName")
        user_tweets_qid = _find_query_id(js.text, "UserTweets")
        if not user_by_name_qid or not user_tweets_qid:
            if debug:
                print("[x] query ids not found")
            return results

        api_headers = {
            "Authorization": f"Bearer {bearer}",
            "x-csrf-token": ct0,
            "x-twitter-auth-type": "OAuth2Session",
        }

        def _get(url: str, variables: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            params = {
                "variables": json.dumps(variables, separators=(",", ":")),
                "features": json.dumps({}, separators=(",", ":")),
            }
            resp = client.get(url, headers=api_headers, params=params)
            if resp.status_code != 200:
                if debug:
                    print(f"[x] graphql status={resp.status_code} body={resp.text[:200]}")
                return None
            return resp.json()

        user_url = f"https://x.com/i/api/graphql/{user_by_name_qid}/UserByScreenName"
        user_data = _get(user_url, {"screen_name": username})
        if not user_data:
            return results
        user_id = (
            user_data.get("data", {})
            .get("user", {})
            .get("result", {})
            .get("rest_id")
        )
        if not user_id:
            if debug:
                print("[x] user id not found")
            return results

        tweets_url = f"https://x.com/i/api/graphql/{user_tweets_qid}/UserTweets"
        tweets_data = _get(tweets_url, {"userId": user_id, "count": max(limit * 2, 20)})
        if not tweets_data:
            return results

        instructions = (
            tweets_data.get("data", {})
            .get("user", {})
            .get("result", {})
            .get("timeline_v2", {})
            .get("timeline", {})
            .get("instructions", [])
        )
        entries = []
        for inst in instructions:
            if inst.get("type") in ("TimelineAddEntries", "TimelineReplaceEntry"):
                entries.extend(inst.get("entries") or [])

        for entry in entries:
            if len(results) >= limit:
                break
            content = entry.get("content", {})
            item = content.get("itemContent", {})
            tweet = (
                item.get("tweet_results", {})
                .get("result", {})
            )
            if not isinstance(tweet, dict):
                continue
            legacy = tweet.get("legacy") or {}
            media = (legacy.get("extended_entities") or {}).get("media") or []
            video_media = None
            for m in media:
                if m.get("type") in ("video", "animated_gif"):
                    video_media = m
                    break
            if not video_media:
                continue
            video_url = _pick_variant(video_media)
            if not video_url:
                continue
            tweet_id = legacy.get("id_str") or legacy.get("id") or tweet.get("rest_id")
            if not tweet_id:
                continue
            tweet_url = f"https://x.com/{username}/status/{tweet_id}"
            description = (legacy.get("full_text") or "").strip()
            created = legacy.get("created_at")
            results.append(
                {
                    "tweet_url": tweet_url,
                    "video_url": video_url,
                    "description": description,
                    "created_at": created,
                }
            )
    return results


def scrape_user_videos(
    username: str,
    limit: int,
    debug: bool = False,
    nitter_bases: Optional[List[str]] = None,
    cookies: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if cookies:
        items = _scrape_with_authenticated_graphql(username, limit, cookies, debug=debug)
        if items:
            return items
        items = _scrape_with_cookie_html(username, limit, cookies)
        if items:
            return items
    try:
        items = _scrape_with_snscrape(username, limit)
        if items:
            return items
    except Exception:
        pass
    items = _scrape_with_guest_api(username, limit, debug=debug)
    if items:
        return items
    items = _scrape_with_nitter(username, limit, bases=nitter_bases)
    if items:
        return items
    return _scrape_with_ytdlp_user(username, limit, cookies=cookies)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape X video URLs and descriptions (no Selenium).")
    parser.add_argument("--user", required=True, help="X username (without @)")
    parser.add_argument("--limit", type=int, default=15, help="Max videos to return")
    parser.add_argument("--debug", action="store_true", help="Print debug info")
    parser.add_argument(
        "--nitter",
        action="append",
        help="Add custom Nitter/FXTwitter base URL (can repeat).",
    )
    parser.add_argument(
        "--cookies",
        help="Path to cookies.txt (Netscape format) for authenticated scraping.",
    )
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    items = scrape_user_videos(
        args.user,
        args.limit,
        debug=args.debug,
        nitter_bases=args.nitter,
        cookies=args.cookies,
    )
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    out_path = DATA_DIR / f"x_videos_{args.user}_{stamp}.json"
    out_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"OK: {len(items)} items")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
