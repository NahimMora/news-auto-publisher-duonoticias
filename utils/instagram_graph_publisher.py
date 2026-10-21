"""Publish Instagram posts using Graph API (images + carousel + reels)."""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import List, Optional


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
from utils.http_client import HttpClient
from utils import media_storage
DATA_DIR = BASE_DIR / "data"

def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv(BASE_DIR / ".env")

IG_GRAPH_VERSION = os.getenv("IG_GRAPH_VERSION", "v18.0")
# META_* is the canonical .env naming (storage/settings.py); IG_*/FB_* stay as fallbacks.
IG_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN") or os.getenv("IG_ACCESS_TOKEN")
IG_USER_ID = os.getenv("META_IG_USER_ID") or os.getenv("IG_USER_ID")
IG_MEDIA_BASE_URL = os.getenv("IG_MEDIA_BASE_URL")
MEDIA_STORAGE_PROVIDER = os.getenv("MEDIA_STORAGE_PROVIDER", "").strip().lower() or "cloudinary"
IG_PUBLISH_VIDEOS = os.getenv("IG_PUBLISH_VIDEOS", "1") != "0"
IG_VIDEO_AS_REEL = os.getenv("IG_VIDEO_AS_REEL", "1") != "0"
CLOUDINARY_DELETE_AFTER_PUBLISH = os.getenv("CLOUDINARY_DELETE_AFTER_PUBLISH", "1") != "0"
IG_PUBLISH_DUPLICATE_REELS = os.getenv("IG_PUBLISH_DUPLICATE_REELS", "1") != "0"
IG_NETWORK_RETRIES = int(os.getenv("IG_NETWORK_RETRIES", "5"))
IG_NETWORK_BACKOFF_BASE = float(os.getenv("IG_NETWORK_BACKOFF_BASE", "5"))
IG_NETWORK_BACKOFF_MAX = float(os.getenv("IG_NETWORK_BACKOFF_MAX", "120"))
IG_PUBLISHED_HISTORY_PATH = os.getenv(
    "IG_PUBLISHED_HISTORY_PATH",
    str(DATA_DIR / "noticias_publicadas_instagram.json"),
)
FB_FALLBACK_ENABLED = os.getenv("FB_FALLBACK_ON_IG_LIMIT", "1") != "0"
FB_PAGE_ID = os.getenv("META_PAGE_ID") or os.getenv("FB_PAGE_ID")
FB_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN") or os.getenv("FB_ACCESS_TOKEN") or IG_ACCESS_TOKEN

CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")
CLOUDINARY_UPLOAD_FOLDER = os.getenv("CLOUDINARY_UPLOAD_FOLDER", "duo_noticias")
CLOUDINARY_TIMEOUT = int(os.getenv("CLOUDINARY_TIMEOUT", "180"))
CLOUDINARY_RETRY_DOWNSCALE = os.getenv("CLOUDINARY_RETRY_DOWNSCALE", "1") != "0"
CLOUDINARY_RETRY_MAX_SIZE_MB = float(os.getenv("CLOUDINARY_RETRY_MAX_SIZE_MB", "30"))

_cloudinary_cache = {}
_media_storage_cache = {}
_published_cache = None


def _new_http_client(timeout: int) -> HttpClient:
    return HttpClient(
        timeout=timeout,
        retries=1,
        retry_statuses=(),
        block_statuses=(),
        backoff_base=IG_NETWORK_BACKOFF_BASE,
        backoff_max=IG_NETWORK_BACKOFF_MAX,
    )

def _load_published_keys() -> set:
    global _published_cache
    if _published_cache is not None:
        return _published_cache
    path = Path(IG_PUBLISHED_HISTORY_PATH)
    if not path.exists():
        _published_cache = set()
        return _published_cache
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            _published_cache = set(str(x) for x in data)
        else:
            _published_cache = set()
    except Exception:
        _published_cache = set()
    return _published_cache


def _save_published_keys(keys: set) -> None:
    path = Path(IG_PUBLISHED_HISTORY_PATH)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sorted(keys), ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _get_item_key(item: dict) -> Optional[str]:
    if not isinstance(item, dict):
        return None
    if item.get("ig_key"):
        return str(item.get("ig_key"))
    parts = [
        item.get("source_url") or "",
        item.get("titulo") or "",
    ]
    media = item.get("imagenes_locales") or item.get("imagenes_url") or []
    if media:
        parts.append(str(media[0]))
    raw = "|".join(str(p) for p in parts if p)
    if not raw:
        return None
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _latest_news_file() -> Optional[Path]:
    files = list(DATA_DIR.glob("noticias_instagram_*.json"))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _selected_media_storage_provider() -> str:
    return (MEDIA_STORAGE_PROVIDER or os.getenv("MEDIA_STORAGE_PROVIDER") or "").strip().lower() or "cloudinary"


def _resolve_media_url(path_or_url: str, *, folder_kind: str = "temp") -> Optional[str]:
    if not path_or_url:
        return None
    if str(path_or_url).startswith("http"):
        return path_or_url
    local_path = str(Path(path_or_url))
    if not os.path.exists(local_path):
        print(f"[WARN] Media local no encontrado: {local_path}")
        return None
    provider = _selected_media_storage_provider()
    if provider == "r2":
        if local_path in _media_storage_cache:
            return _media_storage_cache[local_path].get("url")
        uploaded = media_storage.upload_file(local_path, folder_kind="site" if folder_kind == "site" else "temp")
        _media_storage_cache[local_path] = uploaded
        print(f"[R2] Subido: {Path(local_path).name} -> {str(uploaded.get('url') or '')[:80]}...")
        return uploaded.get("url")
    if local_path in _cloudinary_cache:
        return _cloudinary_cache[local_path].get("url")
    if CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
        uploaded = _cloudinary_upload(local_path)
        if uploaded:
            _cloudinary_cache[local_path] = uploaded
            return uploaded.get("url")
    if IG_MEDIA_BASE_URL:
        filename = Path(path_or_url).name
        return f"{IG_MEDIA_BASE_URL.rstrip('/')}/{filename}"
    return None


def _cloudinary_signature(params: dict) -> str:
    payload = "&".join(f"{k}={params[k]}" for k in sorted(params))
    to_sign = f"{payload}{CLOUDINARY_API_SECRET}"
    return hashlib.sha1(to_sign.encode("utf-8")).hexdigest()


def _cloudinary_upload(file_path: str) -> Optional[dict]:
    if not os.path.exists(file_path):
        return None
    ext = Path(file_path).suffix.lower()
    is_video = ext in {".mp4", ".mov", ".m4v", ".webm"}
    resource = "video" if is_video else "image"
    if not (CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET):
        return None

    url = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/{resource}/upload"
    timestamp = int(time.time())
    params = {
        "folder": CLOUDINARY_UPLOAD_FOLDER,
        "timestamp": timestamp,
    }
    signature = _cloudinary_signature(params)
    data = {
        "api_key": CLOUDINARY_API_KEY,
        "timestamp": timestamp,
        "signature": signature,
        "folder": CLOUDINARY_UPLOAD_FOLDER,
    }
    last_error = None
    retries = max(1, IG_NETWORK_RETRIES)
    client = _new_http_client(CLOUDINARY_TIMEOUT)
    try:
        for attempt in range(retries):
            try:
                with open(file_path, "rb") as f:
                    files = {"file": f}
                    resp = client.post(url, data=data, files=files)
            except Exception as exc:
                last_error = exc
                if attempt < retries - 1:
                    if _should_downscale(file_path, exc):
                        reduced = _downscale_video(file_path)
                        if reduced and reduced != file_path:
                            file_path = reduced
                            ext = Path(file_path).suffix.lower()
                            is_video = ext in {".mp4", ".mov", ".m4v", ".webm"}
                            resource = "video" if is_video else "image"
                            url = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/{resource}/upload"
                            data = {
                                "api_key": CLOUDINARY_API_KEY,
                                "timestamp": timestamp,
                                "signature": signature,
                                "folder": CLOUDINARY_UPLOAD_FOLDER,
                            }
                    _sleep_backoff(attempt)
                    continue
                raise RuntimeError(f"Cloudinary upload failed: {exc}")
            try:
                payload = resp.json()
            except Exception:
                payload = {"error": {"message": resp.text}}
            if resp.status_code < 400:
                cloud_url = payload.get("secure_url") or payload.get("url")
                if not cloud_url or not cloud_url.startswith("http"):
                    last_error = {"error": "Cloudinary returned invalid URL", "payload": payload}
                    if attempt < retries - 1:
                        _sleep_backoff(attempt)
                        continue
                    raise RuntimeError(f"Cloudinary upload failed: {last_error}")
                print(f"[Cloudinary] Subido: {Path(file_path).name} -> {cloud_url[:80]}...")
                return {
                    "url": cloud_url,
                    "public_id": payload.get("public_id"),
                    "resource_type": payload.get("resource_type") or resource,
                }
            last_error = payload
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                _sleep_backoff(attempt)
                continue
            break
    finally:
        client.close()
    raise RuntimeError(f"Cloudinary upload failed: {last_error}")


def _should_downscale(file_path: str, exc: Exception) -> bool:
    if not CLOUDINARY_RETRY_DOWNSCALE:
        return False
    if not _is_video_file(file_path):
        return False
    size_mb = _file_size_mb(file_path)
    if size_mb is None or size_mb < CLOUDINARY_RETRY_MAX_SIZE_MB:
        return False
    message = str(exc).lower()
    return "timeout" in message or "timed out" in message or "connection aborted" in message


def _file_size_mb(path: str) -> Optional[float]:
    try:
        return os.path.getsize(path) / (1024 * 1024)
    except Exception:
        return None


def _is_video_file(path: str) -> bool:
    ext = Path(path).suffix.lower()
    return ext in {".mp4", ".mov", ".m4v", ".webm"}


def _downscale_video(path: str) -> Optional[str]:
    try:
        from utils.video_processor import process_video_for_instagram
    except Exception:
        return None
    try:
        temp_dir = DATA_DIR / "tmp_downscale"
        temp_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(path).stem
        out_path = temp_dir / f"{stem}_reduced.mp4"
        processed = process_video_for_instagram(
            path,
            str(out_path),
            template_path=None,
            enable_subtitles=False,
            quality="borrador",
            title_text=None,
            output_mode=os.getenv("IG_VIDEO_OUTPUT_MODE", "reel"),
        )
        return processed
    except Exception:
        return None

def _cloudinary_delete(local_path: str) -> bool:
    info = _cloudinary_cache.get(local_path)
    if not info:
        return False
    public_id = info.get("public_id")
    resource = info.get("resource_type") or "image"
    if not public_id:
        return False
    if not (CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET):
        return False
    url = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/{resource}/destroy"
    timestamp = int(time.time())
    params = {"public_id": public_id, "timestamp": timestamp}
    signature = _cloudinary_signature(params)
    data = {
        "public_id": public_id,
        "timestamp": timestamp,
        "api_key": CLOUDINARY_API_KEY,
        "signature": signature,
    }
    client = _new_http_client(60)
    try:
        resp = client.post(url, data=data)
        payload = resp.json()
        result = payload.get("result")
        ok = result in ("ok", "not found")
        if ok:
            _cloudinary_cache.pop(local_path, None)
        return ok
    except Exception:
        return False
    finally:
        client.close()

def _cleanup_cloudinary(local_paths: List[str]) -> None:
    if _selected_media_storage_provider() == "r2":
        for path in {p for p in local_paths if p}:
            info = _media_storage_cache.get(str(Path(path)))
            if not info:
                continue
            try:
                ok = media_storage.delete_uploaded(info)
            except Exception:
                ok = False
            if ok:
                _media_storage_cache.pop(str(Path(path)), None)
                print(f"R2 eliminado: {Path(path).name}")
        return
    if not CLOUDINARY_DELETE_AFTER_PUBLISH:
        return
    for path in {p for p in local_paths if p}:
        ok = _cloudinary_delete(path)
        if ok:
            print(f"Cloudinary eliminado: {Path(path).name}")


def _graph_post(path: str, data: dict) -> dict:
    if not IG_ACCESS_TOKEN:
        raise RuntimeError("Missing IG_ACCESS_TOKEN")
    url = f"https://graph.facebook.com/{IG_GRAPH_VERSION}{path}"
    payload = {**data, "access_token": IG_ACCESS_TOKEN}
    last_error = None
    retries = max(1, IG_NETWORK_RETRIES)
    client = _new_http_client(60)
    try:
        for attempt in range(retries):
            try:
                resp = client.post(url, data=payload)
            except Exception as exc:
                last_error = _sanitize_error(str(exc))
                if attempt < retries - 1:
                    _sleep_backoff(attempt)
                    continue
                raise RuntimeError(last_error)
            try:
                response_payload = resp.json()
            except Exception:
                response_payload = {"error": {"message": resp.text}}
            error = response_payload.get("error")
            if resp.status_code < 400 and not error:
                return response_payload
            if error and _graph_error_retryable(error) and attempt < retries - 1:
                _sleep_backoff(attempt)
                continue
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                _sleep_backoff(attempt)
                continue
            last_error = response_payload
            break
    finally:
        client.close()
    raise RuntimeError(f"Graph API error: {last_error}")


def _graph_get(path: str, params: dict) -> dict:
    if not IG_ACCESS_TOKEN:
        raise RuntimeError("Missing IG_ACCESS_TOKEN")
    url = f"https://graph.facebook.com/{IG_GRAPH_VERSION}{path}"
    payload = {**params, "access_token": IG_ACCESS_TOKEN}
    last_error = None
    retries = max(1, IG_NETWORK_RETRIES)
    client = _new_http_client(60)
    try:
        for attempt in range(retries):
            try:
                resp = client.get(url, params=payload)
            except Exception as exc:
                last_error = _sanitize_error(str(exc))
                if attempt < retries - 1:
                    _sleep_backoff(attempt)
                    continue
                raise RuntimeError(last_error)
            try:
                response_payload = resp.json()
            except Exception:
                response_payload = {"error": {"message": resp.text}}
            error = response_payload.get("error")
            if resp.status_code < 400 and not error:
                return response_payload
            if error and _graph_error_retryable(error) and attempt < retries - 1:
                _sleep_backoff(attempt)
                continue
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                _sleep_backoff(attempt)
                continue
            last_error = response_payload
            break
    finally:
        client.close()
    raise RuntimeError(f"Graph API error: {last_error}")


def _fb_graph_post(path: str, data: dict) -> dict:
    if not FB_ACCESS_TOKEN:
        raise RuntimeError("Missing FB_ACCESS_TOKEN")
    url = f"https://graph.facebook.com/{IG_GRAPH_VERSION}{path}"
    payload = {**data, "access_token": FB_ACCESS_TOKEN}
    last_error = None
    retries = max(1, IG_NETWORK_RETRIES)
    client = _new_http_client(60)
    try:
        for attempt in range(retries):
            try:
                resp = client.post(url, data=payload)
            except Exception as exc:
                last_error = _sanitize_error(str(exc))
                if attempt < retries - 1:
                    _sleep_backoff(attempt)
                    continue
                raise RuntimeError(last_error)
            try:
                response_payload = resp.json()
            except Exception:
                response_payload = {"error": {"message": resp.text}}
            error = response_payload.get("error")
            if resp.status_code < 400 and not error:
                return response_payload
            if error and _graph_error_retryable(error) and attempt < retries - 1:
                _sleep_backoff(attempt)
                continue
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                _sleep_backoff(attempt)
                continue
            last_error = response_payload
            break
    finally:
        client.close()
    raise RuntimeError(f"Facebook Graph API error: {last_error}")


def _is_ig_media_limit_error(exc_text: str) -> bool:
    text = (exc_text or "").lower()
    return (
        "user is performing too many actions" in text
        or "se superó el límite de publicaciones de contenido multimedia" in text
        or "'error_subcode': 2207042" in text
        or '"error_subcode": 2207042' in text
    )


def _publish_via_facebook_fallback(item: dict) -> Optional[str]:
    if not FB_FALLBACK_ENABLED or not FB_PAGE_ID:
        return None

    caption = (item.get("texto_instagram") or item.get("caption") or "").strip()
    images = item.get("imagenes_locales") or item.get("imagenes_url") or []
    videos = item.get("videos_locales") or item.get("videos_url") or []

    image_urls = [u for u in (_resolve_media_url(x) for x in images) if u]
    video_urls = [u for u in (_resolve_media_url(x) for x in videos) if u]

    if video_urls:
        data = {"file_url": video_urls[0], "description": caption}
        result = _fb_graph_post(f"/{FB_PAGE_ID}/videos", data)
        return result.get("id")
    if image_urls:
        data = {"url": image_urls[0], "caption": caption, "published": "true"}
        result = _fb_graph_post(f"/{FB_PAGE_ID}/photos", data)
        return result.get("post_id") or result.get("id")

    data = {"message": caption or (item.get("titulo") or "Actualización")}
    result = _fb_graph_post(f"/{FB_PAGE_ID}/feed", data)
    return result.get("id")


def _wait_container(container_id: str, timeout_sec: int = 600) -> None:
    start = time.time()
    poll_interval = 5
    while True:
        try:
            status = _graph_get(
                f"/{container_id}",
                {"fields": "status_code,status,error_message"},
            )
        except RuntimeError as exc:
            msg = str(exc)
            if "error_message" in msg and "nonexisting field" in msg:
                print(f"[IG] Warning: error_message no disponible para {container_id}. Reintentando sin ese campo.")
                status = _graph_get(
                    f"/{container_id}",
                    {"fields": "status_code,status"},
                )
            else:
                raise
        code = status.get("status_code")
        if code in ("FINISHED", "PUBLISHED"):
            time.sleep(3)
            return
        if code == "ERROR":
            err = status.get("error_message") or status.get("error") or "sin detalle"
            print(f"[IG] Container ERROR {container_id}: {err}")
            print(f"[IG] Container payload: {status}")
            raise RuntimeError(f"Container error: {status}")
        if code == "IN_PROGRESS":
            poll_interval = min(poll_interval + 2, 15)
        if time.time() - start > timeout_sec:
            raise RuntimeError(f"Timeout waiting for container {container_id}")
        time.sleep(poll_interval)


def _create_media_container(
    media_url: str,
    media_kind: str,
    caption: Optional[str] = None,
    is_carousel: bool = False,
    force_reel: Optional[bool] = None,
) -> str:
    print(f"[IG] media_url: {media_url}")
    if media_kind == "video":
        data = {"video_url": media_url}
        if is_carousel:
            data["media_type"] = "VIDEO"
        elif force_reel is True:
            data["media_type"] = "REELS"
        elif force_reel is False:
            data["media_type"] = "VIDEO"
        elif IG_VIDEO_AS_REEL:
            data["media_type"] = "REELS"
        else:
            data["media_type"] = "VIDEO"
    else:
        data = {"image_url": media_url}

    if caption and not is_carousel:
        data["caption"] = caption
    if is_carousel:
        data["is_carousel_item"] = "true"
    result = _graph_post(f"/{IG_USER_ID}/media", data)
    return result["id"]


def _publish_container(container_id: str) -> str:
    result = _graph_post(f"/{IG_USER_ID}/media_publish", {"creation_id": container_id})
    return result.get("id")


def _publish_carousel(items: List[dict], caption: str) -> Optional[str]:
    if not items:
        return None
    if len(items) == 1:
        item = items[0]
        media_kind = item.get("type") or "image"
        src = item.get("path") or item.get("url")
        if not src:
            return None
        local_paths = []
        if not str(src).startswith("http"):
            local_paths.append(str(Path(src)))
        media_url = _resolve_media_url(src)
        if not media_url:
            return None
        container_id = _create_media_container(media_url, media_kind, caption=caption)
        if media_kind == "video":
            _wait_container(container_id)
        post_id = _publish_container(container_id)
        if post_id:
            _cleanup_cloudinary(local_paths)
        return post_id
    child_ids: List[str] = []
    local_paths: List[str] = []
    for item in items[:10]:
        media_kind = item.get("type") or "image"
        src = item.get("path") or item.get("url")
        if not src:
            continue
        if not str(src).startswith("http"):
            local_paths.append(str(Path(src)))
        media_url = _resolve_media_url(src)
        if not media_url:
            continue
        container_id = _create_media_container(media_url, media_kind, is_carousel=True)
        if media_kind == "video":
            _wait_container(container_id)
        child_ids.append(container_id)

    if not child_ids:
        return None

    carousel = _graph_post(
        f"/{IG_USER_ID}/media",
        {"media_type": "CAROUSEL", "children": ",".join(child_ids), "caption": caption},
    )
    container_id = carousel["id"]
    _wait_container(container_id)
    post_id = _publish_container(container_id)
    if post_id:
        _cleanup_cloudinary(local_paths)
    return post_id


def publish_item(item: dict) -> Optional[str]:
    caption = item.get("texto_instagram") or ""
    key = _get_item_key(item)
    if key:
        published = _load_published_keys()
        if key in published:
            print("Saltado: ya publicado")
            return None

    carousel_items = item.get("carousel_media") or []
    if carousel_items:
        post_id = _publish_carousel(carousel_items, caption)
        _publish_reels(item, caption)
        if post_id and key:
            published = _load_published_keys()
            published.add(key)
            _save_published_keys(published)
        return post_id

    images = item.get("imagenes_locales") or item.get("imagenes_url") or []
    video_items = item.get("videos_locales") or item.get("videos_url") or []

    if images and video_items:
        combo = [{"type": "image", "path": p} for p in images[:1]]
        combo.extend({"type": "video", "path": v} for v in video_items)
        post_id = _publish_carousel(combo, caption)
        _publish_reels(item, caption)
        if post_id and key:
            published = _load_published_keys()
            published.add(key)
            _save_published_keys(published)
        return post_id

    image_urls = [u for u in (_resolve_media_url(x) for x in images) if u]
    local_images = [str(Path(p)) for p in images if p and not str(p).startswith("http")]

    video_urls = [u for u in (_resolve_media_url(x) for x in video_items) if u]
    local_videos = [str(Path(p)) for p in video_items if p and not str(p).startswith("http")]

    if IG_PUBLISH_VIDEOS and video_urls:
        force_feed = bool(item.get("reels"))
        container_id = _create_media_container(video_urls[0], "video", caption=caption, force_reel=(False if force_feed else None))
        _wait_container(container_id)
        post_id = _publish_container(container_id)
        if post_id:
            _cleanup_cloudinary(local_videos)
        _publish_reels(item, caption)
        if post_id and key:
            published = _load_published_keys()
            published.add(key)
            _save_published_keys(published)
        return post_id

    if not image_urls:
        return None

    if len(image_urls) == 1:
        container_id = _create_media_container(image_urls[0], "image", caption=caption)
        _wait_container(container_id)
        post_id = _publish_container(container_id)
        if post_id:
            _cleanup_cloudinary(local_images)
        _publish_reels(item, caption)
        if post_id and key:
            published = _load_published_keys()
            published.add(key)
            _save_published_keys(published)
        return post_id

    child_ids: List[str] = []
    for url in image_urls[:10]:
        child_ids.append(_create_media_container(url, "image", is_carousel=True))

    carousel = _graph_post(
        f"/{IG_USER_ID}/media",
        {"media_type": "CAROUSEL", "children": ",".join(child_ids), "caption": caption},
    )
    container_id = carousel["id"]
    _wait_container(container_id)
    post_id = _publish_container(container_id)
    if post_id:
        _cleanup_cloudinary(local_images)
    _publish_reels(item, caption)
    if post_id and key:
        published = _load_published_keys()
        published.add(key)
        _save_published_keys(published)
    return post_id


def _publish_reels(item: dict, caption: str) -> None:
    if not IG_PUBLISH_DUPLICATE_REELS:
        return
    reels = item.get("reels") or []
    if not reels:
        return
    for reel in reels:
        src = reel.get("path") if isinstance(reel, dict) else reel
        if not src:
            continue
        local_paths = []
        if not str(src).startswith("http"):
            local_paths.append(str(Path(src)))
        media_url = _resolve_media_url(src)
        if not media_url:
            continue
        try:
            container_id = _create_media_container(media_url, "video", caption=caption, force_reel=True)
            _wait_container(container_id)
            post_id = _publish_container(container_id)
            if post_id:
                print(f"Publicado Reel: {post_id}")
                _cleanup_cloudinary(local_paths)
                key = _get_item_key(item)
                if key:
                    published = _load_published_keys()
                    published.add(key + ":reel")
                    _save_published_keys(published)
        except Exception as exc:
            print(f"[ERROR] Reel fallo: {_sanitize_error(str(exc))}")


def _sanitize_error(text: str) -> str:
    if not text:
        return text
    return re.sub(r"access_token=[^&\\s]+", "access_token=***", text)


def _graph_error_retryable(error: dict) -> bool:
    if not isinstance(error, dict):
        return False
    code = error.get("code")
    subcode = error.get("error_subcode")
    message = (error.get("message") or "").lower()
    if code in (4, 17, 32, 613):
        return True
    if subcode in (99, 33):
        return True
    if any(token in message for token in ("rate limit", "throttle", "temporarily", "retry")):
        return True
    return False


def _sleep_backoff(attempt: int) -> None:
    base = max(0.5, IG_NETWORK_BACKOFF_BASE)
    delay = min(IG_NETWORK_BACKOFF_MAX, base * (2 ** attempt))
    time.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish Instagram posts via Graph API.")
    parser.add_argument("--file", help="Path to noticias_instagram_*.json (optional)")
    parser.add_argument("--max", type=int, default=None, help="Max items to publish")
    args = parser.parse_args()

    if not IG_USER_ID:
        raise RuntimeError("Missing IG_USER_ID")

    data_file = Path(args.file) if args.file else _latest_news_file()
    if not data_file or not data_file.exists():
        print("No noticias_instagram_*.json found in data/")
        return

    with open(data_file, "r", encoding="utf-8") as f:
        items = json.load(f)

    if isinstance(items, dict):
        items = items.get("items") or items.get("noticias") or []

    count = 0
    for item in items:
        try:
            post_id = publish_item(item)
            if post_id:
                print(f"Publicado: {post_id}")
            else:
                print("Saltado: sin URLs publicas")
        except Exception as exc:
            err = _sanitize_error(str(exc))
            print(f"[ERROR] Publicacion fallo: {err}")
            if _is_ig_media_limit_error(err):
                try:
                    fb_post_id = _publish_via_facebook_fallback(item)
                    if fb_post_id:
                        print(f"[FALLBACK FB] Publicado: {fb_post_id}")
                        key = _get_item_key(item)
                        if key:
                            published = _load_published_keys()
                            published.add(key)
                            _save_published_keys(published)
                    else:
                        print("[FALLBACK FB] No configurado o sin media disponible.")
                except Exception as fb_exc:
                    print(f"[FALLBACK FB ERROR] {_sanitize_error(str(fb_exc))}")
        count += 1
        if args.max and count >= args.max:
            break


if __name__ == "__main__":
    main()
