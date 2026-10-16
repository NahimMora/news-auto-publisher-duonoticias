from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jobs.manual_x_video_flow import ManualXVideoFlow, split_x_links, stable_content_key
from storage.models import ExtractedContent, FormattedPackage, PublicationRecord
from storage.settings import get_settings
from storage.sqlite_store import PipelineStore


class FakePublisher:
    def __init__(self) -> None:
        self.last_like_platform = ""
        self.last_reply_platform = ""

    def like_comments(self, platform: str, comment_ids: list[str]) -> list[dict]:
        self.last_like_platform = platform
        return [
            {
                "comment_id": comment_id,
                "liked": True,
                "supported": True,
                "reason": "",
            }
            for comment_id in comment_ids
        ]

    def reply_comments(self, platform: str, comment_ids: list[str], message: str) -> list[dict]:
        self.last_reply_platform = platform
        return [
            {
                "comment_id": comment_id,
                "replied": True,
                "supported": True,
                "reply_id": f"reply-{comment_id}",
                "payload": {"message": message},
            }
            for comment_id in comment_ids
        ]


class ManualXVideoFlowTests(unittest.TestCase):
    def test_split_x_links_accepts_lines_and_commas(self) -> None:
        raw = "https://x.com/a/status/1\nhttps://x.com/b/status/2, https://x.com/c/status/3"
        self.assertEqual(
            split_x_links(raw),
            [
                "https://x.com/a/status/1",
                "https://x.com/b/status/2",
                "https://x.com/c/status/3",
            ],
        )

    def test_stable_content_key_is_deterministic(self) -> None:
        first = stable_content_key("123", "https://twitter.com/i/status/123")
        second = stable_content_key("123", "https://twitter.com/i/status/123")
        other = stable_content_key("124", "https://twitter.com/i/status/124")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)

    def test_comment_actions_are_persisted_for_selected_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_manual_x_") as tmp_dir:
            db_path = Path(tmp_dir) / "duo.sqlite3"
            with patch.dict(os.environ, {"DUO_DB_PATH": str(db_path)}):
                get_settings.cache_clear()
                settings = get_settings()
                store = PipelineStore(settings)
                content = ExtractedContent(
                    source="x_manual",
                    source_type="x_video",
                    source_item_id="123",
                    canonical_url="https://twitter.com/i/status/123",
                    title="Titulo",
                    summary="Caption",
                    media_type="video",
                    content_key=stable_content_key("123", "https://twitter.com/i/status/123"),
                )
                key = store.upsert_content(content)
                store.save_formatted(key, FormattedPackage(content_key=key, post_type="reel", caption="Caption"))
                publication_id = store.save_publication(
                    key,
                    PublicationRecord(
                        platform="facebook",
                        status="published",
                        platform_media_id="fb-post-1",
                        platform_post_id="fb-post-1",
                        post_type="reel",
                        caption="Caption",
                        published_at="2026-04-07T10:00:00+00:00",
                    ),
                )
                publisher = FakePublisher()
                flow = ManualXVideoFlow(settings=settings, store=store, publisher=publisher)
                comments = [{"id": "c1", "author_username": "ana", "text": "buenisimo"}]

                like_results = flow.like_comments(publication_id, comments)
                reply_results = flow.reply_to_comments(publication_id, comments, "\U0001F525")

                self.assertEqual(publisher.last_like_platform, "facebook")
                self.assertEqual(publisher.last_reply_platform, "facebook")
                self.assertTrue(like_results[0]["liked"])
                self.assertTrue(reply_results[0]["replied"])

                with store.connection() as conn:
                    row = conn.execute(
                        "SELECT liked, replied, reply_id FROM comment_actions WHERE comment_id = ?",
                        ("c1",),
                    ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row["liked"], 1)
                self.assertEqual(row["replied"], 1)
                self.assertEqual(row["reply_id"], "reply-c1")

    def test_list_publications_only_returns_instagram_and_facebook(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_manual_x_") as tmp_dir:
            db_path = Path(tmp_dir) / "duo.sqlite3"
            with patch.dict(os.environ, {"DUO_DB_PATH": str(db_path)}):
                get_settings.cache_clear()
                settings = get_settings()
                store = PipelineStore(settings)
                content = ExtractedContent(
                    source="x_manual",
                    source_type="x_video",
                    source_item_id="123",
                    canonical_url="https://twitter.com/i/status/123",
                    title="Titulo",
                    summary="Caption",
                    media_type="video",
                    content_key=stable_content_key("123", "https://twitter.com/i/status/123"),
                )
                key = store.upsert_content(content)
                store.save_formatted(key, FormattedPackage(content_key=key, post_type="reel", caption="Caption"))
                store.save_publication(
                    key,
                    PublicationRecord(
                        platform="instagram",
                        status="published",
                        platform_media_id="ig-1",
                        platform_post_id="ig-1",
                        post_type="reel",
                        caption="Caption",
                        published_at="2026-04-07T10:00:00+00:00",
                    ),
                )
                store.save_publication(
                    key,
                    PublicationRecord(
                        platform="instagram_story",
                        status="published",
                        platform_media_id="story-1",
                        platform_post_id="story-1",
                        post_type="story",
                        caption="",
                        published_at="2026-04-07T10:05:00+00:00",
                    ),
                )
                flow = ManualXVideoFlow(settings=settings, store=store, publisher=FakePublisher())
                rows = flow.list_publications()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["platform"], "instagram")


if __name__ == "__main__":
    unittest.main()
