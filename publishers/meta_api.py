from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

from storage.models import Asset, FormattedPackage, PublicationRecord
from storage.settings import PipelineSettings, get_settings
from utils.http_client import HttpClient
import utils.instagram_graph_publisher as legacy_ig


class MetaGraphPublisher:
    def __init__(self, settings: PipelineSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.base_url = f"https://graph.facebook.com/{self.settings.ig_graph_version}"
        self._fb_page_id_cache = self.settings.fb_page_id
        self._fb_page_access_token_cache = ""

    def publish_instagram(self, package: FormattedPackage, scheduled_for: str = "") -> PublicationRecord:
        if not self.settings.enable_instagram:
            return PublicationRecord(
                platform="instagram",
                status="unavailable",
                caption=package.caption,
                post_type=package.post_type,
                scheduled_for=scheduled_for,
                error_message="Instagram publishing disabled by ENABLE_INSTAGRAM=false",
                mode="disabled",
            )
        if not self._has_permission("instagram_content_publish"):
            return PublicationRecord(
                platform="instagram",
                status="unavailable",
                caption=package.caption,
                post_type=package.post_type,
                scheduled_for=scheduled_for,
                error_message="Missing configured permission: instagram_content_publish",
                mode="permission_missing",
            )
        try:
            limit_state = self.get_ig_publish_limit()
            if limit_state.get("remaining") == 0:
                raise RuntimeError("Instagram publishing limit reached")
            media_id = self._publish_instagram(package)
            permalink = self._get_instagram_permalink(media_id)
            return PublicationRecord(
                platform="instagram",
                status="published",
                platform_media_id=media_id,
                platform_post_id=media_id,
                permalink=permalink,
                caption=package.caption,
                post_type=package.post_type,
                scheduled_for=scheduled_for,
                published_at=self._utc_now(),
                mode="live",
                payload={"limit_state": limit_state},
            )
        except Exception as exc:
            return PublicationRecord(
                platform="instagram",
                status="failed",
                caption=package.caption,
                post_type=package.post_type,
                scheduled_for=scheduled_for,
                error_message=str(exc),
                mode="live",
                payload={},
            )
        finally:
            self._maybe_cleanup_package_assets(package)

    def publish_facebook(self, package: FormattedPackage, scheduled_for: str = "") -> PublicationRecord:
        if not self.settings.enable_facebook:
            return PublicationRecord(
                platform="facebook",
                status="unavailable",
                caption=package.caption,
                post_type=package.post_type,
                scheduled_for=scheduled_for,
                error_message="Facebook publishing disabled by ENABLE_FACEBOOK=false",
                mode="disabled",
            )
        if not self._has_permission("pages_manage_posts"):
            return PublicationRecord(
                platform="facebook",
                status="unavailable",
                caption=package.caption,
                post_type=package.post_type,
                scheduled_for=scheduled_for,
                error_message="Missing configured permission: pages_manage_posts",
                mode="permission_missing",
            )
        try:
            record = self._publish_facebook_direct(package, scheduled_for=scheduled_for)
            if record:
                return record
        except Exception as exc:
            return PublicationRecord(
                platform="facebook",
                status="failed",
                caption=package.caption,
                post_type=package.post_type,
                scheduled_for=scheduled_for,
                error_message=str(exc),
                mode="live",
                payload={},
            )
        finally:
            self._maybe_cleanup_package_assets(package)
        return PublicationRecord(
            platform="facebook",
            status="failed",
            caption=package.caption,
            post_type=package.post_type,
            scheduled_for=scheduled_for,
            error_message="Missing Facebook credentials",
            mode="live",
            payload={},
        )

    def publish_instagram_story(self, package: FormattedPackage, scheduled_for: str = "") -> PublicationRecord:
        if not self._has_permission("instagram_content_publish"):
            return PublicationRecord(
                platform="instagram_story",
                status="unavailable",
                caption="",
                post_type="story",
                scheduled_for=scheduled_for,
                error_message="Missing configured permission: instagram_content_publish",
                mode="permission_missing",
            )
        try:
            media_id = self._publish_instagram_story(package)
            return PublicationRecord(
                platform="instagram_story",
                status="published",
                platform_media_id=media_id,
                platform_post_id=media_id,
                caption="",
                post_type="story",
                scheduled_for=scheduled_for,
                published_at=self._utc_now(),
                mode="live",
                payload={},
            )
        except Exception as exc:
            return PublicationRecord(
                platform="instagram_story",
                status="failed",
                caption="",
                post_type="story",
                scheduled_for=scheduled_for,
                error_message=str(exc),
                mode="live",
                payload={},
            )
        finally:
            self._maybe_cleanup_package_assets(package)

    def publish(self, package: FormattedPackage, scheduled_for: str = "") -> PublicationRecord:
        try:
            sentinel = object()
            previous_defer = package.meta.get("defer_cleanup", sentinel)
            package.meta["defer_cleanup"] = True
            record = self.publish_instagram(package, scheduled_for=scheduled_for)
            if record.status == "published":
                return record
            exc = record.error_message or "instagram_publish_failed"
            try:
                fb_record = self._publish_facebook_fallback(package, scheduled_for=scheduled_for, error=str(exc))
                if fb_record:
                    return fb_record
            except Exception:
                pass
            return record
        finally:
            if "previous_defer" in locals():
                if previous_defer is sentinel:
                    package.meta.pop("defer_cleanup", None)
                else:
                    package.meta["defer_cleanup"] = previous_defer
            self._maybe_cleanup_package_assets(package)

    def find_recent_publication(self, platform: str, caption: str) -> Dict[str, Any] | None:
        """Busca en la cuenta una publicacion reciente con este caption exacto.

        Devuelve {"id", "permalink"} si existe, {} si se verifico que no existe y
        lanza excepcion si no se pudo verificar (queda "ambiguous").
        """
        wanted = _caption_key(caption)
        if not wanted:
            return None
        if platform == "instagram":
            if not (self.settings.ig_access_token and self.settings.ig_user_id):
                raise RuntimeError("sin credenciales de Instagram para reconciliar")
            payload = self._request(
                "GET",
                f"/{self.settings.ig_user_id}/media",
                params={"fields": "id,caption,permalink,timestamp", "limit": 30},
                access_token=self.settings.ig_access_token,
            )
            for item in payload.get("data") or []:
                if _caption_key(item.get("caption")) == wanted:
                    return {"id": str(item.get("id") or ""), "permalink": str(item.get("permalink") or "")}
            return {}
        if platform == "facebook":
            page_id = self._get_fb_page_id() or self.settings.fb_page_id
            token = self._get_fb_publish_token()
            if not (page_id and token):
                raise RuntimeError("sin credenciales de Facebook para reconciliar")
            for edge, field in (("published_posts", "message"), ("videos", "description")):
                payload = self._request(
                    "GET",
                    f"/{page_id}/{edge}",
                    params={"fields": f"id,{field},permalink_url,created_time", "limit": 30},
                    access_token=token,
                )
                for item in payload.get("data") or []:
                    if _caption_key(item.get(field)) == wanted:
                        return {"id": str(item.get("id") or ""), "permalink": str(item.get("permalink_url") or "")}
            return {}
        raise RuntimeError(f"reconciliacion no soportada para {platform}")

    def get_ig_publish_limit(self) -> Dict[str, Any]:
        if not (self.settings.ig_access_token and self.settings.ig_user_id):
            return {}
        payload = self._request(
            "GET",
            f"/{self.settings.ig_user_id}/content_publishing_limit",
            params={},
            access_token=self.settings.ig_access_token,
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, list) and data:
            current = data[0]
            quota = int(current.get("quota_total") or 100)
            used = int(current.get("quota_usage") or current.get("usage") or 0)
            return {"quota_total": quota, "quota_usage": used, "remaining": max(0, quota - used)}
        return {}

    def engage_instagram_comments(self, media_id: str, reply_emoji: str) -> List[Dict[str, Any]]:
        if not self.settings.enable_comment_engagement:
            return []
        if not self._has_permission("instagram_manage_comments"):
            return []
        comments = self._request(
            "GET",
            f"/{media_id}/comments",
            params={"fields": "id,text,timestamp,username"},
            access_token=self.settings.ig_access_token,
        ).get("data", [])
        actions: List[Dict[str, Any]] = []
        for comment in comments:
            comment_id = str(comment.get("id") or "")
            if not comment_id:
                continue
            reply = self._request(
                "POST",
                f"/{comment_id}/replies",
                data={"message": reply_emoji},
                access_token=self.settings.ig_access_token,
            )
            actions.append(
                {
                    "comment_id": comment_id,
                    "author_username": str(comment.get("username") or ""),
                    "comment_text": str(comment.get("text") or ""),
                    "liked": False,
                    "replied": True,
                    "reply_id": str(reply.get("id") or ""),
                    "payload": {
                        "reply": reply,
                        "like_supported": False,
                        "like_reason": "Instagram Platform comment likes are not documented as supported",
                    },
                }
            )
        return actions

    def collect_instagram_metrics(
        self,
        media_id: str,
        *,
        permalink: str = "",
        published_at: str = "",
    ) -> Dict[str, Any]:
        if not self._has_permission("instagram_basic"):
            return {"details": {}, "insights": {}, "errors": {"permission": "Missing configured permission: instagram_basic"}}
        requested_media_id = media_id
        resolved_media_id = media_id
        errors: Dict[str, Any] = {}
        try:
            details = self._request(
                "GET",
                f"/{resolved_media_id}",
                params={"fields": "id,caption,comments_count,like_count,media_product_type,media_type,permalink,timestamp"},
                access_token=self.settings.ig_access_token,
            )
        except Exception as exc:
            errors["details"] = str(exc)
            fallback_media_id = self._resolve_instagram_media_id(
                media_id=requested_media_id,
                permalink=permalink,
                published_at=published_at,
            )
            if fallback_media_id and fallback_media_id != requested_media_id:
                resolved_media_id = fallback_media_id
                try:
                    details = self._request(
                        "GET",
                        f"/{resolved_media_id}",
                        params={"fields": "id,caption,comments_count,like_count,media_product_type,media_type,permalink,timestamp"},
                        access_token=self.settings.ig_access_token,
                    )
                    errors.pop("details", None)
                except Exception as retry_exc:
                    errors["details"] = str(retry_exc)
                    details = {}
            else:
                details = {}
        metrics = {
            "details": details,
            "insights": {},
            "meta": {
                "requested_media_id": requested_media_id,
                "resolved_media_id": resolved_media_id,
            },
        }
        if errors:
            metrics["errors"] = errors
        if not details:
            return metrics
        requested_metrics = [
            "reach",
            "saved",
            "shares",
            "views",
            "total_interactions",
            "likes",
            "comments",
        ]
        for metric in requested_metrics:
            try:
                response = self._request(
                    "GET",
                    f"/{resolved_media_id}/insights",
                    params={"metric": metric},
                    access_token=self.settings.ig_access_token,
                )
            except Exception as exc:
                metrics.setdefault("errors", {}).setdefault("insights", {})[metric] = str(exc)
                continue
            metrics["insights"][metric] = response.get("data", [])
        return metrics

    def collect_facebook_metrics(self, post_id: str) -> Dict[str, Any]:
        if not self._has_permission("pages_read_engagement"):
            return {"errors": {"permission": "Missing configured permission: pages_read_engagement"}}
        fb_token = self._get_fb_publish_token()
        return self._request(
            "GET",
            f"/{post_id}",
            params={"fields": "id,permalink_url,comments.limit(0).summary(true),likes.limit(0).summary(true)"},
            access_token=fb_token,
        )

    def fetch_publication_comments(
        self,
        platform: str,
        publication_id: str,
        *,
        permalink: str = "",
        published_at: str = "",
    ) -> List[Dict[str, Any]]:
        platform = (platform or "").strip().lower()
        if not publication_id:
            return []
        if platform == "instagram":
            resolved_id = publication_id
            try:
                payload = self._request(
                    "GET",
                    f"/{resolved_id}/comments",
                    params={"fields": "id,text,timestamp,username"},
                    access_token=self.settings.ig_access_token,
                )
            except Exception:
                resolved_id = self.resolve_instagram_media_id(
                    media_id=publication_id,
                    permalink=permalink,
                    published_at=published_at,
                )
                if not resolved_id:
                    raise
                payload = self._request(
                    "GET",
                    f"/{resolved_id}/comments",
                    params={"fields": "id,text,timestamp,username"},
                    access_token=self.settings.ig_access_token,
                )
            return [
                {
                    "id": str(item.get("id") or ""),
                    "author_username": str(item.get("username") or ""),
                    "text": str(item.get("text") or ""),
                    "timestamp": str(item.get("timestamp") or ""),
                    "like_supported": False,
                    "reply_supported": True,
                }
                for item in (payload.get("data") or [])
                if isinstance(item, dict)
            ]
        if platform == "facebook":
            if not self._get_fb_page_id():
                return []
            fb_token = self._get_fb_publish_token()
            payload = self._request(
                "GET",
                f"/{publication_id}/comments",
                params={"fields": "id,message,created_time,from"},
                access_token=fb_token,
            )
            return [
                {
                    "id": str(item.get("id") or ""),
                    "author_username": str(((item.get("from") or {}).get("name")) or ""),
                    "text": str(item.get("message") or ""),
                    "timestamp": str(item.get("created_time") or ""),
                    "like_supported": True,
                    "reply_supported": True,
                }
                for item in (payload.get("data") or [])
                if isinstance(item, dict)
            ]
        return []

    def like_comments(self, platform: str, comment_ids: Iterable[str]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        normalized_platform = (platform or "").strip().lower()
        for comment_id in comment_ids:
            comment_id = str(comment_id or "").strip()
            if not comment_id:
                continue
            if normalized_platform != "facebook":
                results.append(
                    {
                        "comment_id": comment_id,
                        "liked": False,
                        "supported": False,
                        "reason": "Instagram Graph API no expone likes de comentarios",
                    }
                )
                continue
            try:
                fb_token = self._get_fb_publish_token()
                payload = self._request(
                    "POST",
                    f"/{comment_id}/likes",
                    data={},
                    access_token=fb_token,
                )
                results.append(
                    {
                        "comment_id": comment_id,
                        "liked": True,
                        "supported": True,
                        "reason": "",
                        "payload": payload,
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "comment_id": comment_id,
                        "liked": False,
                        "supported": False,
                        "reason": str(exc),
                    }
                )
        return results

    def reply_comments(self, platform: str, comment_ids: Iterable[str], message: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        normalized_platform = (platform or "").strip().lower()
        reply_text = str(message or "").strip()
        if not reply_text:
            return results
        for comment_id in comment_ids:
            comment_id = str(comment_id or "").strip()
            if not comment_id:
                continue
            try:
                if normalized_platform == "instagram":
                    payload = self._request(
                        "POST",
                        f"/{comment_id}/replies",
                        data={"message": reply_text},
                        access_token=self.settings.ig_access_token,
                    )
                elif normalized_platform == "facebook":
                    fb_token = self._get_fb_publish_token()
                    payload = self._request(
                        "POST",
                        f"/{comment_id}/comments",
                        data={"message": reply_text},
                        access_token=fb_token,
                    )
                else:
                    results.append(
                        {
                            "comment_id": comment_id,
                            "replied": False,
                            "supported": False,
                            "reason": f"Unsupported platform: {normalized_platform}",
                        }
                    )
                    continue
                results.append(
                    {
                        "comment_id": comment_id,
                        "replied": True,
                        "supported": True,
                        "reply_id": str(payload.get("id") or ""),
                        "payload": payload,
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "comment_id": comment_id,
                        "replied": False,
                        "supported": False,
                        "reason": str(exc),
                    }
                )
        return results

    def _publish_instagram(self, package: FormattedPackage) -> str:
        if not (self.settings.ig_access_token and self.settings.ig_user_id):
            raise RuntimeError("Missing Instagram credentials")
        if package.post_type == "reel":
            video = next(asset for asset in package.assets if asset.kind == "video")
            upload_mode = os.getenv("IG_REELS_UPLOAD_MODE", "resumable").strip().lower()
            local_video = Path(video.path) if video.path else None
            if upload_mode != "url" and local_video and local_video.exists():
                try:
                    container_id, upload_uri = self._create_reel_resumable_container(package.caption)
                    self._upload_resumable_video(container_id, local_video, upload_uri)
                except Exception:
                    container_id = self._create_reel_url_container(video, package.caption)
            else:
                container_id = self._create_reel_url_container(video, package.caption)
            self._wait_container(container_id)
            media_id = self._publish_container(container_id)
            return media_id
        if package.post_type == "image":
            image = next(asset for asset in package.assets if asset.kind == "image")
            media_url = self._asset_media_url(image)
            container_id = self._create_media_container(media_url, "image", caption=package.caption)
            self._wait_container(container_id)
            media_id = self._publish_container(container_id)
            return media_id
        return self._publish_carousel(package)

    def _publish_instagram_story(self, package: FormattedPackage) -> str:
        if not (self.settings.ig_access_token and self.settings.ig_user_id):
            raise RuntimeError("Missing Instagram credentials")
        story_asset = next((asset for asset in package.assets if asset.kind in {"video", "image"}), None)
        if story_asset is None:
            raise RuntimeError("No media available for story publish")
        media_url = self._asset_media_url(story_asset)
        media_kind = story_asset.kind
        container_id = self._create_media_container(
            media_url,
            media_kind,
            media_type="STORIES",
        )
        self._wait_container(container_id)
        media_id = self._publish_container(container_id)
        return media_id

    def _publish_carousel(self, package: FormattedPackage) -> str:
        child_ids: List[str] = []
        cleanup_targets: List[str] = []
        for asset in package.assets[:10]:
            media_url = self._asset_media_url(asset)
            cleanup_targets.append(asset.path)
            child_id = self._create_media_container(
                media_url,
                asset.kind,
                media_type="VIDEO" if asset.kind == "video" else "",
                is_carousel_item=True,
            )
            if asset.kind == "video":
                self._wait_container(child_id)
            child_ids.append(child_id)
        carousel = self._request(
            "POST",
            f"/{self.settings.ig_user_id}/media",
            data={
                "media_type": "CAROUSEL",
                "children": ",".join(child_ids),
                "caption": package.caption,
            },
            access_token=self.settings.ig_access_token,
        )
        container_id = str(carousel.get("id") or "")
        self._wait_container(container_id)
        media_id = self._publish_container(container_id)
        return media_id

    def _create_media_container(
        self,
        media_url: str,
        kind: str,
        *,
        caption: str = "",
        media_type: str = "",
        is_carousel_item: bool = False,
    ) -> str:
        data = {"caption": caption} if caption and not is_carousel_item else {}
        if kind == "video":
            data["video_url"] = media_url
            data["media_type"] = media_type or "VIDEO"
            if data["media_type"] == "REELS":
                data["share_to_feed"] = "true"
        else:
            data["image_url"] = media_url
            if media_type:
                data["media_type"] = media_type
        if is_carousel_item:
            data["is_carousel_item"] = "true"
        payload = self._request(
            "POST",
            f"/{self.settings.ig_user_id}/media",
            data=data,
            access_token=self.settings.ig_access_token,
        )
        return str(payload.get("id") or "")

    def _create_reel_resumable_container(self, caption: str) -> tuple[str, str]:
        data = {
            "media_type": "REELS",
            "upload_type": "resumable",
            "share_to_feed": "true",
            "thumb_offset": os.getenv("IG_REELS_THUMB_OFFSET_MS", "2000"),
        }
        if caption:
            data["caption"] = caption
        payload = self._request(
            "POST",
            f"/{self.settings.ig_user_id}/media",
            data=data,
            access_token=self.settings.ig_access_token,
        )
        container_id = str(payload.get("id") or "")
        if not container_id:
            raise RuntimeError(f"Instagram did not return container id: {payload}")
        return container_id, str(payload.get("uri") or "")

    def _create_reel_url_container(self, video: Asset, caption: str) -> str:
        media_url = self._asset_media_url(video)
        return self._create_media_container(
            media_url,
            "video",
            caption=caption,
            media_type="REELS",
        )

    def _upload_resumable_video(self, container_id: str, local_path: Path, upload_uri: str = "") -> Dict[str, Any]:
        if not local_path.exists():
            raise RuntimeError(f"Video file not found for Instagram upload: {local_path}")
        file_size = local_path.stat().st_size
        if file_size <= 0:
            raise RuntimeError(f"Video file is empty for Instagram upload: {local_path}")

        upload_url = upload_uri or (
            f"https://rupload.facebook.com/ig-api-upload/{self.settings.ig_graph_version}/{container_id}"
        )
        headers = {
            "Authorization": f"OAuth {self.settings.ig_access_token}",
            "offset": "0",
            "file_size": str(file_size),
            "Content-Type": "application/octet-stream",
        }
        retries = max(1, int(os.getenv("IG_RUPLOAD_RETRIES", "3")))
        last_error: Exception | None = None
        for attempt in range(retries):
            client = HttpClient(timeout=300, retries=1, backoff_base=3, backoff_max=20, block_statuses=())
            try:
                with local_path.open("rb") as handle:
                    response = client.post(upload_url, headers=headers, content=handle)
                try:
                    payload = response.json()
                except Exception:
                    payload = {"text": response.text}
                if response.status_code < 400 and not payload.get("error"):
                    return payload
                last_error = RuntimeError(f"Instagram resumable upload failed: {payload}")
            except Exception as exc:
                last_error = exc
            finally:
                client.close()

            if attempt < retries - 1:
                time.sleep(min(30, 3 * (2 ** attempt)))

        raise RuntimeError(str(last_error or "Instagram resumable upload failed"))

    def _publish_container(self, container_id: str) -> str:
        payload = self._request(
            "POST",
            f"/{self.settings.ig_user_id}/media_publish",
            data={"creation_id": container_id},
            access_token=self.settings.ig_access_token,
        )
        return str(payload.get("id") or "")

    def _wait_container(self, container_id: str) -> None:
        started = time.time()
        while True:
            payload = self._request(
                "GET",
                f"/{container_id}",
                params={"fields": "status_code,status"},
                access_token=self.settings.ig_access_token,
            )
            status = str(payload.get("status_code") or "")
            if status in {"FINISHED", "PUBLISHED"}:
                return
            if status == "ERROR":
                raise RuntimeError(f"Container {container_id} failed: {payload}")
            if time.time() - started > 300:
                raise RuntimeError(f"Timeout waiting container {container_id}")
            time.sleep(10)

    def _get_instagram_permalink(self, media_id: str) -> str:
        payload = self._request(
            "GET",
            f"/{media_id}",
            params={"fields": "permalink"},
            access_token=self.settings.ig_access_token,
        )
        return str(payload.get("permalink") or "")

    def _resolve_instagram_media_id(
        self,
        *,
        media_id: str,
        permalink: str = "",
        published_at: str = "",
    ) -> str:
        if not (self.settings.ig_access_token and self.settings.ig_user_id):
            return ""
        try:
            payload = self._request(
                "GET",
                f"/{self.settings.ig_user_id}/media",
                params={
                    "fields": "id,permalink,timestamp,media_product_type,media_type",
                    "limit": 25,
                },
                access_token=self.settings.ig_access_token,
            )
        except Exception:
            return ""
        items = payload.get("data") or []
        if not isinstance(items, list):
            return ""
        permalink = str(permalink or "").strip()
        published_at = str(published_at or "").strip()

        for item in items:
            if not isinstance(item, dict):
                continue
            candidate_id = str(item.get("id") or "").strip()
            candidate_permalink = str(item.get("permalink") or "").strip()
            if candidate_id and candidate_id == media_id:
                return candidate_id
            if permalink and candidate_permalink and candidate_permalink == permalink:
                return candidate_id

        if published_at:
            for item in items:
                if not isinstance(item, dict):
                    continue
                candidate_id = str(item.get("id") or "").strip()
                candidate_timestamp = str(item.get("timestamp") or "").strip()
                if candidate_id and candidate_timestamp and candidate_timestamp == published_at:
                    return candidate_id
        return ""

    def resolve_instagram_media_id(
        self,
        *,
        media_id: str,
        permalink: str = "",
        published_at: str = "",
    ) -> str:
        direct_match = self._resolve_instagram_media_id(
            media_id=media_id,
            permalink=permalink,
            published_at=published_at,
        )
        if direct_match:
            return direct_match
        if not (self.settings.ig_access_token and self.settings.ig_user_id):
            return ""
        after_cursor = ""
        for _ in range(10):
            params = {
                "fields": "id,permalink,timestamp,media_product_type,media_type",
                "limit": 25,
            }
            if after_cursor:
                params["after"] = after_cursor
            try:
                payload = self._request(
                    "GET",
                    f"/{self.settings.ig_user_id}/media",
                    params=params,
                    access_token=self.settings.ig_access_token,
                )
            except Exception:
                return ""
            items = payload.get("data") or []
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    candidate_id = str(item.get("id") or "").strip()
                    candidate_permalink = str(item.get("permalink") or "").strip()
                    candidate_timestamp = str(item.get("timestamp") or "").strip()
                    if candidate_id and candidate_id == media_id:
                        return candidate_id
                    if permalink and candidate_permalink and candidate_permalink == permalink:
                        return candidate_id
                    if published_at and candidate_timestamp and candidate_timestamp == published_at:
                        return candidate_id
            paging = payload.get("paging") or {}
            cursors = paging.get("cursors") or {}
            after_cursor = str(cursors.get("after") or "").strip()
            if not after_cursor:
                break
        return ""

    def _publish_facebook_fallback(
        self,
        package: FormattedPackage,
        *,
        scheduled_for: str,
        error: str,
    ) -> PublicationRecord | None:
        if not self.settings.enable_facebook or not self._has_permission("pages_manage_posts"):
            return None
        record = self._publish_facebook_direct(package, scheduled_for=scheduled_for)
        if record:
            record.mode = "fallback"
            record.payload = {**dict(record.payload), "fallback_from": error}
        return record

    def _publish_facebook_direct(
        self,
        package: FormattedPackage,
        *,
        scheduled_for: str,
    ) -> PublicationRecord | None:
        page_id = self._get_fb_page_id()
        fb_token = self._get_fb_publish_token()
        if not (fb_token and page_id):
            return None
        if package.post_type == "reel":
            video = next(asset for asset in package.assets if asset.kind == "video")
            media_url = self._asset_media_url(video)
            payload = self._request(
                "POST",
                f"/{page_id}/videos",
                data={"file_url": media_url, "description": package.caption},
                access_token=fb_token,
            )
            return PublicationRecord(
                platform="facebook",
                status="published",
                platform_media_id=str(payload.get("id") or ""),
                platform_post_id=str(payload.get("id") or ""),
                caption=package.caption,
                post_type=package.post_type,
                scheduled_for=scheduled_for,
                published_at=self._utc_now(),
                mode="live",
                payload={},
            )
        if package.post_type == "image":
            image = next(asset for asset in package.assets if asset.kind == "image")
            media_url = self._asset_media_url(image)
            payload = self._request(
                "POST",
                f"/{page_id}/photos",
                data={"url": media_url, "caption": package.caption, "published": "true"},
                access_token=fb_token,
            )
            return PublicationRecord(
                platform="facebook",
                status="published",
                platform_media_id=str(payload.get("post_id") or payload.get("id") or ""),
                platform_post_id=str(payload.get("post_id") or payload.get("id") or ""),
                caption=package.caption,
                post_type=package.post_type,
                scheduled_for=scheduled_for,
                published_at=self._utc_now(),
                mode="live",
                payload={},
            )
        image = next(asset for asset in package.assets if asset.kind == "image")
        media_url = self._asset_media_url(image)
        payload = self._request(
            "POST",
            f"/{page_id}/photos",
            data={"url": media_url, "caption": package.caption, "published": "true"},
            access_token=fb_token,
        )
        return PublicationRecord(
            platform="facebook",
            status="published",
            platform_media_id=str(payload.get("post_id") or payload.get("id") or ""),
            platform_post_id=str(payload.get("post_id") or payload.get("id") or ""),
            caption=package.caption,
            post_type=package.post_type,
            scheduled_for=scheduled_for,
            published_at=self._utc_now(),
            mode="live",
            payload={"note": "carousel collapsed to first asset for facebook publish"},
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Dict[str, Any] | None = None,
        data: Dict[str, Any] | None = None,
        access_token: str,
    ) -> Dict[str, Any]:
        client = HttpClient(timeout=60, retries=3, backoff_base=3, backoff_max=20)
        try:
            payload_params = dict(params or {})
            payload_data = dict(data or {})
            if method.upper() == "GET":
                payload_params["access_token"] = access_token
                response = client.get(f"{self.base_url}{path}", params=payload_params)
            else:
                payload_data["access_token"] = access_token
                response = client.post(f"{self.base_url}{path}", data=payload_data)
            parsed = response.json()
            if response.status_code >= 400 or parsed.get("error"):
                raise RuntimeError(str(parsed))
            return parsed
        finally:
            client.close()

    def _asset_media_url(self, asset: Asset) -> str:
        media_ref = asset.remote_url or asset.path
        media_url = legacy_ig._resolve_media_url(media_ref)
        if not media_url:
            raise RuntimeError("No media URL available for publish")
        return media_url

    def _cleanup_assets(self, package: FormattedPackage, local_paths: List[str]) -> None:
        if package.meta.get("skip_cloud_cleanup"):
            return
        legacy_ig._cleanup_cloudinary(local_paths)

    def cleanup_package_assets(self, package: FormattedPackage) -> None:
        local_paths = [asset.path for asset in package.assets if asset.path]
        if not local_paths:
            return
        self._cleanup_assets(package, local_paths)

    def _maybe_cleanup_package_assets(self, package: FormattedPackage) -> None:
        if package.meta.get("defer_cleanup"):
            return
        try:
            self.cleanup_package_assets(package)
        except Exception:
            return

    def _get_fb_page_id(self) -> str:
        if self._fb_page_id_cache:
            return self._fb_page_id_cache
        account = self._get_fb_page_account()
        if not account:
            return ""
        page_id = str(account.get("id") or "").strip()
        if page_id:
            self._fb_page_id_cache = page_id
        return page_id

    def _get_fb_publish_token(self) -> str:
        if self._fb_page_access_token_cache:
            return self._fb_page_access_token_cache
        account = self._get_fb_page_account()
        if not account:
            return self.settings.fb_access_token
        token = str(account.get("access_token") or "").strip()
        if token:
            self._fb_page_access_token_cache = token
            return token
        return self.settings.fb_access_token

    def _get_fb_page_account(self) -> Dict[str, Any]:
        if not self.settings.fb_access_token:
            return {}
        if self._fb_page_id_cache and self._fb_page_access_token_cache:
            return {
                "id": self._fb_page_id_cache,
                "access_token": self._fb_page_access_token_cache,
            }
        try:
            payload = self._request(
                "GET",
                "/me/accounts",
                params={"fields": "id,name,access_token,tasks"},
                access_token=self.settings.fb_access_token,
            )
        except Exception:
            return {}
        rows = payload.get("data") or []
        if not isinstance(rows, list) or not rows:
            return {}
        account = dict(rows[0] or {})
        page_id = str(account.get("id") or "").strip()
        page_token = str(account.get("access_token") or "").strip()
        if page_id:
            self._fb_page_id_cache = page_id
        if page_token:
            self._fb_page_access_token_cache = page_token
        return account

    def _has_permission(self, permission: str) -> bool:
        configured = {item.strip() for item in self.settings.meta_permissions if item.strip()}
        return permission in configured

    @staticmethod
    def _utc_now() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _caption_key(value: object) -> str:
    """Primeros 160 caracteres normalizados: evidencia fuerte (caption generado unico)."""
    text = " ".join(str(value or "").split()).strip().lower()
    return text[:160]
