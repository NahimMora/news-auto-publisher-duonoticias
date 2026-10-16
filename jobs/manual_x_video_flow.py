from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from extractor_x.extractor_x_videos import extract_recent_videos
from publishers.meta_api import MetaGraphPublisher
from scrapping.x.x_action_pipeline import _sanitize_items
from storage.models import Asset, EditorialPackage, ExtractedContent, FormattedPackage
from storage.settings import PipelineSettings, get_settings
from storage.sqlite_store import PipelineStore
from utils.image_processor import normalize_for_instagram_blur
import utils.instagram_graph_publisher as legacy_ig
from utils.video_processor import get_video_duration_seconds, process_video_for_instagram
from utils.x_captioner_openai import format_caption_paragraphs, generate_instagram_metadata


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE_PATH = Path(
    os.getenv(
        "IG_VIDEO_TEMPLATE_PATH",
        str(BASE_DIR / "video_app" / "assets" / "templates" / "hola_salta.json"),
    )
)


def split_x_links(raw_text: str) -> List[str]:
    values: List[str] = []
    for line in (raw_text or "").splitlines():
        for token in line.replace(",", " ").split():
            token = token.strip()
            if token:
                values.append(token)
    return values


def stable_content_key(tweet_id: str, tweet_url: str) -> str:
    raw = f"x_manual|{tweet_id.strip()}|{tweet_url.strip()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


class ManualXVideoFlow:
    def __init__(
        self,
        *,
        settings: PipelineSettings | None = None,
        store: PipelineStore | None = None,
        publisher: MetaGraphPublisher | None = None,
        logger: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.store = store or PipelineStore(self.settings)
        self.publisher = publisher or MetaGraphPublisher(self.settings)
        self.logger = logger or (lambda message: None)
        self.template_path = DEFAULT_TEMPLATE_PATH if DEFAULT_TEMPLATE_PATH.exists() else None
        self.video_use_layout = os.getenv("IG_VIDEO_USE_LAYOUT", "1").strip().lower() not in {"0", "false", "no", "off"}
        self.cookies_path = str(self.settings.base_dir / "scrapping" / "cookies.txt")
        self.output_dir = self.settings.data_dir / "manual_x_reels"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.story_dir = self.settings.data_dir / "manual_x_stories"
        self.story_dir.mkdir(parents=True, exist_ok=True)
        self.manual_quality = os.getenv("IG_VIDEO_QUALITY_MANUAL", "rapido").strip() or "rapido"

    def process_links(
        self,
        links: Iterable[str],
        *,
        publish_instagram: bool,
        publish_facebook: bool,
        publish_story: bool,
    ) -> List[Dict[str, Any]]:
        normalized_links = [str(link).strip() for link in links if str(link).strip()]
        if not normalized_links:
            raise RuntimeError("No hay links de X para procesar")

        self.logger(f"Extrayendo {len(normalized_links)} link(s) de X")
        extracted = extract_recent_videos(
            normalized_links,
            max_videos=len(normalized_links),
            max_age_hours=24 * 365,
            cookies=self.cookies_path if Path(self.cookies_path).exists() else None,
            include_processed=True,
            allow_old_direct_links=True,
        )
        if not extracted:
            raise RuntimeError("No se pudo extraer ningun video desde los links ingresados")

        self.logger(f"Videos extraidos: {len(extracted)}")
        enriched = generate_instagram_metadata(extracted)
        sanitized = _sanitize_items(enriched)
        results: List[Dict[str, Any]] = []
        for index, row in enumerate(sanitized, start=1):
            results.append(
                self._process_item(
                    row,
                    position=index,
                    publish_instagram=publish_instagram,
                    publish_facebook=publish_facebook,
                    publish_story=publish_story,
                )
            )
        return results

    def list_publications(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self.store.connection() as conn:
            rows = conn.execute(
                """
                SELECT p.id, p.content_key, p.platform, p.status, p.platform_media_id, p.platform_post_id,
                       p.permalink, p.caption, p.post_type, p.published_at, p.error_message,
                       c.title, c.source, c.source_handle
                FROM publications p
                JOIN content_items c ON c.content_key = p.content_key
                WHERE p.status = 'published'
                  AND p.platform IN ('instagram', 'facebook')
                ORDER BY COALESCE(p.published_at, p.updated_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def fetch_comments(self, publication_id: int) -> List[Dict[str, Any]]:
        publication = self._get_publication(publication_id)
        graph_platform = self._graph_platform(publication.get("platform"))
        platform_post_id = str(
            publication.get("platform_post_id") or publication.get("platform_media_id") or ""
        )
        if not graph_platform or not platform_post_id:
            return []
        try:
            comments = self.publisher.fetch_publication_comments(
                graph_platform,
                platform_post_id,
                permalink=str(publication.get("permalink") or ""),
                published_at=str(publication.get("published_at") or ""),
            )
            caption = str(publication.get("caption") or "")
            for comment in comments:
                comment_id = str(comment.get("id") or "").strip()
                existing = self._existing_comment_action(graph_platform, comment_id) if comment_id else {}
                liked_local = bool(existing.get("liked"))
                replied_local = bool(existing.get("replied"))
                comment["liked_local"] = liked_local
                comment["replied_local"] = replied_local
                comment["pending_engagement"] = self._is_pending_comment(
                    comment_like_supported=bool(comment.get("like_supported")),
                    liked_local=liked_local,
                    replied_local=replied_local,
                )
                comment["suggested_emoji"] = self._pick_comment_emoji(
                    caption=caption,
                    comment_text=str(comment.get("text") or ""),
                    fallback=self.settings.comment_reply_emoji,
                )
            return comments
        except Exception as exc:
            if graph_platform == "instagram":
                raise RuntimeError(
                    "Ese reel no se puede consultar con el token actual. "
                    "Proba con publicaciones recientes hechas desde esta cuenta."
                ) from exc
            raise

    def like_comments(self, publication_id: int, comments: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        publication = self._get_publication(publication_id)
        graph_platform = self._graph_platform(publication.get("platform"))
        comment_rows = [comment for comment in comments if str(comment.get("id") or "").strip()]
        results = self.publisher.like_comments(
            graph_platform,
            [str(comment["id"]) for comment in comment_rows],
        )
        self._persist_comment_actions(
            publication_id,
            graph_platform,
            comment_rows,
            like_results=results,
            reply_results=[],
        )
        return results

    def reply_to_comments(
        self,
        publication_id: int,
        comments: Iterable[Dict[str, Any]],
        emoji: str,
    ) -> List[Dict[str, Any]]:
        publication = self._get_publication(publication_id)
        graph_platform = self._graph_platform(publication.get("platform"))
        comment_rows = [comment for comment in comments if str(comment.get("id") or "").strip()]
        results = self.publisher.reply_comments(
            graph_platform,
            [str(comment["id"]) for comment in comment_rows],
            emoji,
        )
        self._persist_comment_actions(
            publication_id,
            graph_platform,
            comment_rows,
            like_results=[],
            reply_results=results,
        )
        return results

    def like_and_reply_comments(
        self,
        publication_id: int,
        comments: Iterable[Dict[str, Any]],
        fallback_emoji: str = "",
    ) -> List[Dict[str, Any]]:
        publication = self._get_publication(publication_id)
        graph_platform = self._graph_platform(publication.get("platform"))
        comment_rows = [comment for comment in comments if str(comment.get("id") or "").strip()]
        if not comment_rows:
            return []

        like_results: List[Dict[str, Any]] = []
        if graph_platform == "facebook":
            like_results = self.publisher.like_comments(
                graph_platform,
                [str(comment["id"]) for comment in comment_rows],
            )

        caption = str(publication.get("caption") or "")
        reply_results: List[Dict[str, Any]] = []
        for comment in comment_rows:
            comment_id = str(comment.get("id") or "").strip()
            emoji = self._pick_comment_emoji(
                caption=caption,
                comment_text=str(comment.get("text") or ""),
                fallback=fallback_emoji or self.settings.comment_reply_emoji,
            )
            result = self.publisher.reply_comments(graph_platform, [comment_id], emoji)
            for item in result:
                item["emoji_used"] = emoji
            reply_results.extend(result)

        self._persist_comment_actions(
            publication_id,
            graph_platform,
            comment_rows,
            like_results=like_results,
            reply_results=reply_results,
        )

        by_comment_id: Dict[str, Dict[str, Any]] = {}
        for item in like_results:
            by_comment_id.setdefault(str(item.get("comment_id") or ""), {}).update(item)
        for item in reply_results:
            by_comment_id.setdefault(str(item.get("comment_id") or ""), {}).update(item)
        return [by_comment_id.get(str(comment.get("id") or ""), {}) for comment in comment_rows]

    def _process_item(
        self,
        row: Dict[str, Any],
        *,
        position: int,
        publish_instagram: bool,
        publish_facebook: bool,
        publish_story: bool,
    ) -> Dict[str, Any]:
        tweet_id = str(row.get("tweet_id") or row.get("id") or "").strip()
        tweet_url = str(row.get("tweet_url") or row.get("url") or "").strip()
        if not tweet_id:
            raise RuntimeError("Item sin tweet_id")
        if not tweet_url:
            tweet_url = f"https://twitter.com/i/status/{tweet_id}"

        title = self._normalize_title(str(row.get("titulo_instagram") or row.get("title") or "Video"))
        caption = self._normalize_caption(
            str(row.get("texto_instagram") or row.get("original_text") or "Video")
        )
        source_video_path = str(row.get("video_path") or row.get("file") or "").strip()
        if not source_video_path or not Path(source_video_path).exists():
            raise RuntimeError(f"No existe el video descargado para {tweet_id}")

        content_key = stable_content_key(tweet_id, tweet_url)
        self.logger(f"[{position}] Armando reel {tweet_id}")
        formatted_path = self._build_reel_path(tweet_id)
        if self.video_use_layout and not self.template_path:
            raise RuntimeError(f"No se encontro plantilla de layout de video: {DEFAULT_TEMPLATE_PATH}")
        layout_template = str(self.template_path) if self.video_use_layout and self.template_path else None
        process_video_for_instagram(
            source_video_path,
            str(formatted_path),
            template_path=layout_template,
            enable_subtitles=False,
            quality=self.manual_quality,
            title_text=title,
            output_mode="reel",
        )
        reel_remote_url = legacy_ig._resolve_media_url(str(formatted_path)) or ""
        cleanup_targets = [str(formatted_path)]

        duration = self._coerce_duration(row.get("duration")) or get_video_duration_seconds(str(formatted_path))
        self._persist_content(
            content_key=content_key,
            tweet_id=tweet_id,
            tweet_url=tweet_url,
            author=str(row.get("author") or ""),
            title=title,
            caption=caption,
            original_text=str(row.get("original_text") or ""),
            source_video_path=source_video_path,
            formatted_path=str(formatted_path),
            duration=duration,
            raw_payload=row,
        )

        package = FormattedPackage(
            content_key=content_key,
            post_type="reel",
            caption=caption,
            thumbnail_path="",
            assets=[
                Asset(
                    kind="video",
                    path=str(formatted_path),
                    remote_url=reel_remote_url,
                    duration_seconds=duration,
                    meta={
                        "tweet_id": tweet_id,
                        "tweet_url": tweet_url,
                        "role": "publish",
                    },
                )
            ],
            meta={
                "overlay": title,
                "source": "x_manual",
                "source_video_path": source_video_path,
                "layout_template": layout_template or "",
                "skip_cloud_cleanup": True,
            },
        )
        self.store.save_formatted(content_key, package)
        story_package: FormattedPackage | None = None
        if publish_story:
            story_package = self._build_story_package(content_key=content_key, tweet_id=tweet_id, title=title, caption=caption, video_path=str(formatted_path))
            if story_package.assets:
                story_path = story_package.assets[0].path
                if story_path:
                    cleanup_targets.append(story_path)

        publications: Dict[str, Dict[str, Any]] = {}
        try:
            if publish_instagram:
                self.logger(f"[{position}] Publicando en Instagram {tweet_id}")
                publications["instagram"] = self._publish_once(
                    content_key,
                    package,
                    platform="instagram",
                    action=self.publisher.publish_instagram,
                )
                self.logger(self._publication_log_line(position, tweet_id, "Instagram", publications["instagram"]))
            if publish_facebook:
                self.logger(f"[{position}] Publicando en Facebook {tweet_id}")
                publications["facebook"] = self._publish_once(
                    content_key,
                    package,
                    platform="facebook",
                    action=self.publisher.publish_facebook,
                )
                self.logger(self._publication_log_line(position, tweet_id, "Facebook", publications["facebook"]))
            if publish_story and story_package is not None:
                self.logger(f"[{position}] Publicando historia IG {tweet_id}")
                publications["instagram_story"] = self._publish_once(
                    content_key,
                    story_package,
                    platform="instagram_story",
                    action=self.publisher.publish_instagram_story,
                )
                self.logger(self._publication_log_line(position, tweet_id, "Story", publications["instagram_story"]))
        finally:
            legacy_ig._cleanup_cloudinary(cleanup_targets)

        return {
            "content_key": content_key,
            "tweet_id": tweet_id,
            "tweet_url": tweet_url,
            "title": title,
            "caption": caption,
            "source_video_path": source_video_path,
            "formatted_video_path": str(formatted_path),
            "publications": publications,
        }

    def _build_story_package(
        self,
        *,
        content_key: str,
        tweet_id: str,
        title: str,
        caption: str,
        video_path: str,
    ) -> FormattedPackage:
        thumbnail_path = self._render_video_thumbnail(video_path, self.story_dir / f"{tweet_id}_story_source.jpg")
        if not thumbnail_path:
            raise RuntimeError(f"No se pudo generar thumbnail para story {tweet_id}")
        story_image_path = normalize_for_instagram_blur(
            thumbnail_path,
            output_filename=f"{tweet_id}_story.jpg",
            folder=str(self.story_dir),
            target_size=(1080, 1920),
            title_text=title,
            title_font_path=str(self.settings.base_dir / "media" / "Montserrat-ExtraBold.ttf"),
            watermark_path=str(self.settings.base_dir / "media" / "logo.png"),
            watermark_position="top_right",
            watermark_scale=0.22,
            watermark_opacity=0.9,
        )
        if not story_image_path:
            raise RuntimeError(f"No se pudo generar story para {tweet_id}")
        remote_url = legacy_ig._resolve_media_url(str(story_image_path)) or ""
        return FormattedPackage(
            content_key=content_key,
            post_type="image",
            caption=caption,
            thumbnail_path=str(story_image_path),
            assets=[
                Asset(
                    kind="image",
                    path=str(story_image_path),
                    remote_url=remote_url,
                    meta={"role": "story", "tweet_id": tweet_id},
                )
            ],
            meta={"skip_cloud_cleanup": True, "story_adaptation": True},
        )

    def _persist_content(
        self,
        *,
        content_key: str,
        tweet_id: str,
        tweet_url: str,
        author: str,
        title: str,
        caption: str,
        original_text: str,
        source_video_path: str,
        formatted_path: str,
        duration: Optional[float],
        raw_payload: Dict[str, Any],
    ) -> None:
        content = ExtractedContent(
            source="x_manual",
            source_type="x_video",
            source_item_id=tweet_id,
            canonical_url=tweet_url,
            author=author,
            source_handle=author,
            title=title,
            summary=caption,
            body_text=original_text,
            media_type="video",
            visible_metrics={},
            ranking_signals={"manual_ui": True},
            raw_payload=dict(raw_payload),
            assets=[
                Asset(
                    kind="video",
                    path=source_video_path,
                    duration_seconds=duration,
                    meta={"tweet_url": tweet_url, "formatted_path": formatted_path},
                )
            ],
            content_key=content_key,
        )
        self.store.upsert_content(content)
        editorial = EditorialPackage(
            hook=title,
            context=original_text.strip(),
            tension="",
            remate="",
            cta="",
            caption=caption,
            overlay=title,
            publish=True,
            reason="manual_x_ui",
            angle="manual_x",
            style="duo_manual",
            prompt_used="manual_x_ui_caption",
            input_payload={"tweet_id": tweet_id, "tweet_url": tweet_url},
            feedback_summary="Flujo manual de videos de X sin scoring.",
            hook_type="manual",
            tone="directo",
            pattern_signature=f"manual-x-{tweet_id}",
        )
        self.store.save_editorial(content_key, editorial)

    def _publish_once(
        self,
        content_key: str,
        package: FormattedPackage,
        *,
        platform: str,
        action: Callable[[FormattedPackage], Any],
    ) -> Dict[str, Any]:
        existing = self._existing_publication(content_key, platform)
        if existing:
            return {
                "publication_id": int(existing.get("id") or 0),
                "platform": platform,
                "status": "skipped",
                "reason": "already_published",
                "platform_post_id": str(
                    existing.get("platform_post_id") or existing.get("platform_media_id") or ""
                ),
                "permalink": str(existing.get("permalink") or ""),
            }
        record = action(package)
        publication_id = self.store.save_publication(content_key, record)
        payload = record.as_dict()
        payload["publication_id"] = publication_id
        return payload

    def _existing_publication(self, content_key: str, platform: str) -> Optional[Dict[str, Any]]:
        with self.store.connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM publications
                WHERE content_key = ?
                  AND platform = ?
                  AND status = 'published'
                LIMIT 1
                """,
                (content_key, platform),
            ).fetchone()
        return dict(row) if row else None

    def _get_publication(self, publication_id: int) -> Dict[str, Any]:
        with self.store.connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM publications
                WHERE id = ?
                LIMIT 1
                """,
                (publication_id,),
            ).fetchone()
        if not row:
            raise RuntimeError(f"No existe la publicacion {publication_id}")
        return dict(row)

    def _persist_comment_actions(
        self,
        publication_id: int,
        platform: str,
        comments: List[Dict[str, Any]],
        *,
        like_results: List[Dict[str, Any]],
        reply_results: List[Dict[str, Any]],
    ) -> None:
        by_comment_id: Dict[str, Dict[str, Any]] = {}
        for item in like_results:
            by_comment_id.setdefault(str(item.get("comment_id") or ""), {}).update(item)
        for item in reply_results:
            by_comment_id.setdefault(str(item.get("comment_id") or ""), {}).update(item)

        for comment in comments:
            comment_id = str(comment.get("id") or "").strip()
            if not comment_id:
                continue
            result = by_comment_id.get(comment_id, {})
            existing = self._existing_comment_action(platform, comment_id)
            self.store.save_comment_action(
                publication_id,
                platform=platform,
                comment_id=comment_id,
                author_username=str(comment.get("author_username") or ""),
                comment_text=str(comment.get("text") or ""),
                liked=bool(result.get("liked")) if "liked" in result else bool(existing.get("liked")),
                replied=bool(result.get("replied")) if "replied" in result else bool(existing.get("replied")),
                reply_id=str(result.get("reply_id") or existing.get("reply_id") or ""),
                payload=result,
            )

    def _build_reel_path(self, tweet_id: str) -> Path:
        return self.output_dir / f"{tweet_id}_reel.mp4"

    @staticmethod
    def _publication_log_line(position: int, tweet_id: str, label: str, payload: Dict[str, Any]) -> str:
        status = str(payload.get("status") or "unknown")
        error = str(payload.get("error_message") or payload.get("reason") or "").strip()
        if error:
            return f"[{position}] {label} {tweet_id}: {status} | {error}"
        return f"[{position}] {label} {tweet_id}: {status}"

    @staticmethod
    def _render_video_thumbnail(video_path: str, output_path: Path) -> str:
        import cv2

        capture = cv2.VideoCapture(video_path)
        ok, frame = capture.read()
        capture.release()
        if not ok or frame is None:
            return ""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(output_path), frame)
        return str(output_path)

    def _existing_comment_action(self, platform: str, comment_id: str) -> Dict[str, Any]:
        with self.store.connection() as conn:
            row = conn.execute(
                """
                SELECT liked, replied, reply_id
                FROM comment_actions
                WHERE platform = ?
                  AND comment_id = ?
                LIMIT 1
                """,
                (platform, comment_id),
            ).fetchone()
        return dict(row) if row else {}

    @staticmethod
    def _is_pending_comment(
        *,
        comment_like_supported: bool,
        liked_local: bool,
        replied_local: bool,
    ) -> bool:
        if comment_like_supported:
            return not liked_local
        return not replied_local

    @staticmethod
    def _pick_comment_emoji(*, caption: str, comment_text: str, fallback: str) -> str:
        normalized = f"{caption} {comment_text}".lower()
        keyword_map = (
            (("amor", "romance", "pareja", "novio", "novia", "boda", "beso"), "❤️"),
            (("jaja", "jaj", "grac", "meme", "risa", "divert"), "😂"),
            (("triste", "dolor", "muerte", "lloro", "llorar", "pena"), "😢"),
            (("bronca", "enojo", "indigna", "escandal", "polém", "polem"), "😡"),
            (("viral", "impact", "bomba", "fuerte", "tremendo", "increible"), "🔥"),
            (("sorpresa", "insolito", "wtf", "no puede", "no lo puedo creer"), "😳"),
            (("ternura", "bebe", "bebé", "hijo", "hija", "famil"), "🥹"),
        )
        for keywords, emoji in keyword_map:
            if any(keyword in normalized for keyword in keywords):
                return emoji
        return (fallback or "🔥").strip() or "🔥"

    @staticmethod
    def _graph_platform(platform: Any) -> str:
        value = str(platform or "").strip().lower()
        if value.startswith("facebook"):
            return "facebook"
        if value.startswith("instagram"):
            return "instagram"
        return ""

    @staticmethod
    def _normalize_title(value: str) -> str:
        clean = re.sub(r"\s+", " ", value or "").strip()
        return clean[:80] or "Video"

    @staticmethod
    def _normalize_caption(value: str) -> str:
        clean = format_caption_paragraphs(value)
        return clean[:2200] or "Video"

    @staticmethod
    def _coerce_duration(value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
