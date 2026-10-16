from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from jobs.pipeline import DuoPipeline
from storage.models import Asset, ExtractedContent, FormattedPackage, PublicationRecord, ScheduleDecision
from storage.settings import get_settings


class FakeMetaPublisher:
    def __init__(self) -> None:
        self.instagram_calls = 0
        self.facebook_calls = 0

    def publish_instagram(self, package: FormattedPackage, scheduled_for: str = "") -> PublicationRecord:
        self.instagram_calls += 1
        return PublicationRecord(
            platform="instagram",
            status="published",
            platform_media_id=f"ig-{self.instagram_calls}",
            platform_post_id=f"ig-{self.instagram_calls}",
            caption=package.caption,
            post_type=package.post_type,
            scheduled_for=scheduled_for,
            published_at="2026-04-07T09:00:00+00:00",
        )

    def publish_facebook(self, package: FormattedPackage, scheduled_for: str = "") -> PublicationRecord:
        self.facebook_calls += 1
        return PublicationRecord(
            platform="facebook",
            status="published",
            platform_media_id=f"fb-{self.facebook_calls}",
            platform_post_id=f"fb-{self.facebook_calls}",
            caption=package.caption,
            post_type=package.post_type,
            scheduled_for=scheduled_for,
            published_at="2026-04-07T09:00:00+00:00",
        )


class CleanupAwarePublisher:
    def __init__(self) -> None:
        self.defer_during_publish: list[object] = []
        self.cleanup_calls = 0
        self.defer_during_cleanup: list[object] = []

    def publish_instagram(self, package: FormattedPackage, scheduled_for: str = "") -> PublicationRecord:
        self.defer_during_publish.append(package.meta.get("defer_cleanup"))
        return PublicationRecord(platform="instagram", status="published", scheduled_for=scheduled_for)

    def publish_facebook(self, package: FormattedPackage, scheduled_for: str = "") -> PublicationRecord:
        self.defer_during_publish.append(package.meta.get("defer_cleanup"))
        return PublicationRecord(platform="facebook", status="published", scheduled_for=scheduled_for)

    def cleanup_package_assets(self, package: FormattedPackage) -> None:
        self.cleanup_calls += 1
        self.defer_during_cleanup.append(package.meta.get("defer_cleanup"))


class SlotCapturingPipeline(DuoPipeline):
    def __init__(self, settings):
        super().__init__(settings)
        self.run_publisher_kwargs = None

    def run_publisher(self, **kwargs):  # type: ignore[override]
        self.run_publisher_kwargs = kwargs
        return 0


class PipelinePublishingTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_settings.cache_clear()

    def test_due_item_publishes_to_instagram_and_facebook(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_publish_") as tmp_dir:
            db_path = Path(tmp_dir) / "duo.sqlite3"
            with patch.dict(
                os.environ,
                {
                    "DUO_DB_PATH": str(db_path),
                    "DUO_LIVE_PUBLISH_ENABLED": "1",
                    "COMPUTERNAME": "FERNANDO",
                    "DUO_SAFE_MODE_DEFAULT": "0",
                    "ENABLE_INSTAGRAM": "1",
                    "ENABLE_FACEBOOK": "1",
                    "DUO_PUBLISH_DEFAULT_MAX_POSTS": "8",
                },
                clear=False,
            ):
                get_settings.cache_clear()
                pipeline = DuoPipeline(get_settings())
                fake_publisher = FakeMetaPublisher()
                pipeline.publisher = fake_publisher  # type: ignore[assignment]
                now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                key = pipeline.store.upsert_content(
                    ExtractedContent(
                        source="news",
                        source_type="article",
                        source_item_id="1",
                        canonical_url="https://example.com/1",
                        title="El Gobierno anuncio una medida politica",
                        summary="El Congreso analizara el proyecto durante la jornada.",
                        media_type="image",
                        created_at=now,
                    )
                )
                pipeline.store.save_formatted(
                    key,
                    FormattedPackage(content_key=key, post_type="image", caption="Caption"),
                )
                pipeline.store.save_schedule(
                    key,
                    ScheduleDecision(
                        scheduled_for=now,
                        slot_label="09:00",
                        priority_rank=1,
                        reason="test",
                    ),
                )

                self.assertEqual(pipeline.run_publisher(safe_mode=False), 1)

                statuses = pipeline.store.publication_statuses(key)
                row = pipeline.store.find_content(key)
                assert row is not None
                self.assertEqual(statuses["instagram"]["status"], "published")
                self.assertEqual(statuses["facebook"]["status"], "published")
                self.assertEqual(row["pipeline_status"], "published")
                self.assertEqual(fake_publisher.instagram_calls, 1)
                self.assertEqual(fake_publisher.facebook_calls, 1)

    def test_run_publisher_skips_already_published_platform(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_publish_") as tmp_dir:
            db_path = Path(tmp_dir) / "duo.sqlite3"
            with patch.dict(
                os.environ,
                {
                    "DUO_DB_PATH": str(db_path),
                    "DUO_LIVE_PUBLISH_ENABLED": "1",
                    "COMPUTERNAME": "FERNANDO",
                    "DUO_SAFE_MODE_DEFAULT": "0",
                    "ENABLE_INSTAGRAM": "1",
                    "ENABLE_FACEBOOK": "1",
                    "DUO_PUBLISH_DEFAULT_MAX_POSTS": "8",
                },
                clear=False,
            ):
                get_settings.cache_clear()
                pipeline = DuoPipeline(get_settings())
                fake_publisher = FakeMetaPublisher()
                pipeline.publisher = fake_publisher  # type: ignore[assignment]
                now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                key = pipeline.store.upsert_content(
                    ExtractedContent(
                        source="news",
                        source_type="article",
                        source_item_id="2",
                        canonical_url="https://example.com/2",
                        title="La policia detuvo a una banda tras un allanamiento",
                        summary="El operativo policial ocurrio durante la jornada.",
                        media_type="image",
                        created_at=now,
                    )
                )
                pipeline.store.save_formatted(
                    key,
                    FormattedPackage(content_key=key, post_type="image", caption="Caption"),
                )
                pipeline.store.save_publication(
                    key,
                    PublicationRecord(
                        platform="instagram",
                        status="published",
                        platform_media_id="ig-existing",
                        platform_post_id="ig-existing",
                    ),
                )
                pipeline.store.save_schedule(
                    key,
                    ScheduleDecision(
                        scheduled_for=now,
                        slot_label="09:00",
                        priority_rank=1,
                        reason="test",
                    ),
                )

                self.assertEqual(pipeline.run_publisher(safe_mode=False), 1)

                statuses = pipeline.store.publication_statuses(key)
                self.assertEqual(statuses["instagram"]["platform_post_id"], "ig-existing")
                self.assertEqual(statuses["facebook"]["status"], "published")
                self.assertEqual(fake_publisher.instagram_calls, 0)
                self.assertEqual(fake_publisher.facebook_calls, 1)

    def test_run_publisher_blocks_reel_without_required_layout(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_publish_") as tmp_dir:
            db_path = Path(tmp_dir) / "duo.sqlite3"
            video_path = Path(tmp_dir) / "source.mp4"
            video_path.write_bytes(b"0" * 60000)
            with patch.dict(
                os.environ,
                {
                    "DUO_DB_PATH": str(db_path),
                    "DUO_LIVE_PUBLISH_ENABLED": "1",
                    "COMPUTERNAME": "FERNANDO",
                    "DUO_SAFE_MODE_DEFAULT": "0",
                    "ENABLE_INSTAGRAM": "1",
                    "ENABLE_FACEBOOK": "1",
                    "IG_VIDEO_USE_LAYOUT": "1",
                },
                clear=False,
            ):
                get_settings.cache_clear()
                pipeline = DuoPipeline(get_settings())
                fake_publisher = FakeMetaPublisher()
                pipeline.publisher = fake_publisher  # type: ignore[assignment]
                now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                key = pipeline.store.upsert_content(
                    ExtractedContent(
                        source="x",
                        source_type="x_video",
                        source_item_id="3",
                        canonical_url="https://x.com/test/status/3",
                        title="Video politico de seguridad con debate",
                        summary="El Gobierno y la policia quedaron en el centro de la discusion.",
                        body_text="El Gobierno y la policia quedaron en el centro de la discusion publica por un operativo.",
                        media_type="video",
                        created_at=now,
                    )
                )
                pipeline.store.save_formatted(
                    key,
                    FormattedPackage(
                        content_key=key,
                        post_type="reel",
                        caption="Caption",
                        assets=[Asset(kind="video", path=str(video_path))],
                        meta={"style": "legacy_video_formatter"},
                    ),
                )
                pipeline.store.save_schedule(
                    key,
                    ScheduleDecision(
                        scheduled_for=now,
                        slot_label="09:00",
                        priority_rank=1,
                        reason="test",
                    ),
                )

                self.assertEqual(pipeline.run_publisher(safe_mode=False), 0)

                row = pipeline.store.find_content(key)
                assert row is not None
                self.assertEqual(row["pipeline_status"], "format_failed")
                self.assertEqual(row["last_error"], "video_layout_missing_rebuild_required")
                self.assertEqual(fake_publisher.instagram_calls, 0)
                self.assertEqual(fake_publisher.facebook_calls, 0)

    def test_run_publisher_allows_recent_x_video_from_previous_local_day(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_publish_") as tmp_dir:
            db_path = Path(tmp_dir) / "duo.sqlite3"
            video_path = Path(tmp_dir) / "source.mp4"
            video_path.write_bytes(b"0" * 60000)
            with patch.dict(
                os.environ,
                {
                    "DUO_DB_PATH": str(db_path),
                    "DUO_LIVE_PUBLISH_ENABLED": "1",
                    "COMPUTERNAME": "FERNANDO",
                    "DUO_SAFE_MODE_DEFAULT": "0",
                    "ENABLE_INSTAGRAM": "1",
                    "ENABLE_FACEBOOK": "1",
                    "IG_VIDEO_USE_LAYOUT": "0",
                    "DUO_PUBLISH_REQUIRE_SAME_LOCAL_DAY": "1",
                    "DUO_X_REQUIRE_SAME_LOCAL_DAY": "0",
                },
                clear=False,
            ):
                get_settings.cache_clear()
                pipeline = DuoPipeline(get_settings())
                fake_publisher = FakeMetaPublisher()
                pipeline.publisher = fake_publisher  # type: ignore[assignment]
                now = datetime.now(timezone.utc).replace(microsecond=0)
                created_at = (now - timedelta(hours=10)).isoformat()
                scheduled_for = now.isoformat()
                key = pipeline.store.upsert_content(
                    ExtractedContent(
                        source="x",
                        source_type="x_video",
                        source_item_id="x-previous-day",
                        canonical_url="https://x.com/test/status/x-previous-day",
                        source_handle="ceciarmy",
                        title="Video viral de anoche con fuerte debate",
                        summary="El clip sigue fresco y mantiene interacciones altas.",
                        media_type="video",
                        created_at=created_at,
                        assets=[Asset(kind="video", path=str(video_path))],
                    )
                )
                pipeline.store.save_formatted(
                    key,
                    FormattedPackage(
                        content_key=key,
                        post_type="reel",
                        caption="Caption",
                        assets=[Asset(kind="video", path=str(video_path))],
                    ),
                )
                pipeline.store.save_schedule(
                    key,
                    ScheduleDecision(
                        scheduled_for=scheduled_for,
                        slot_label="09:00",
                        priority_rank=1,
                        reason="test",
                    ),
                )

                published = pipeline.run_publisher(safe_mode=False)

                row = pipeline.store.find_content(key)
                assert row is not None
                self.assertEqual(published, 1)
                self.assertEqual(row["pipeline_status"], "published")
                self.assertEqual(fake_publisher.instagram_calls, 1)
                self.assertEqual(fake_publisher.facebook_calls, 1)

    def test_fixed_slot_publish_defers_outside_active_slot(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_publish_") as tmp_dir:
            db_path = Path(tmp_dir) / "duo.sqlite3"
            with patch.dict(
                os.environ,
                {
                    "DUO_DB_PATH": str(db_path),
                    "DUO_LIVE_PUBLISH_ENABLED": "1",
                    "COMPUTERNAME": "FERNANDO",
                    "ENABLE_INSTAGRAM": "1",
                    "ENABLE_FACEBOOK": "1",
                },
                clear=False,
            ):
                get_settings.cache_clear()
                pipeline = DuoPipeline(get_settings())
                fake_publisher = FakeMetaPublisher()
                pipeline.publisher = fake_publisher  # type: ignore[assignment]
                key = pipeline.store.upsert_content(
                    ExtractedContent(
                        source="news",
                        source_type="article",
                        source_item_id="3",
                        canonical_url="https://example.com/3",
                        title="El Gobierno anuncio una medida politica",
                        summary="El Congreso analizara el proyecto durante la jornada.",
                        media_type="image",
                    )
                )
                pipeline.store.save_formatted(
                    key,
                    FormattedPackage(content_key=key, post_type="image", caption="Caption"),
                )
                pipeline.store.save_schedule(
                    key,
                    ScheduleDecision(
                        scheduled_for="2026-04-07T09:00:00+00:00",
                        slot_label="09:00",
                        priority_rank=1,
                        reason="test",
                    ),
                )

                with patch.object(pipeline, "_active_schedule_slot", return_value=None):
                    self.assertEqual(pipeline.run_publisher(safe_mode=False, fixed_slot_only=True), 0)

                row = pipeline.store.find_content(key)
                assert row is not None
                self.assertEqual(row["pipeline_status"], "scheduled")
                self.assertEqual(fake_publisher.instagram_calls, 0)
                self.assertEqual(fake_publisher.facebook_calls, 0)

    def test_fixed_slot_publish_uses_overdue_backlog_when_active_slot_is_empty(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_publish_") as tmp_dir:
            db_path = Path(tmp_dir) / "duo.sqlite3"
            with patch.dict(
                os.environ,
                {
                    "DUO_DB_PATH": str(db_path),
                    "DUO_LIVE_PUBLISH_ENABLED": "1",
                    "COMPUTERNAME": "FERNANDO",
                    "ENABLE_INSTAGRAM": "1",
                    "ENABLE_FACEBOOK": "1",
                },
                clear=False,
            ):
                get_settings.cache_clear()
                pipeline = DuoPipeline(get_settings())
                fake_publisher = FakeMetaPublisher()
                pipeline.publisher = fake_publisher  # type: ignore[assignment]
                now = datetime.now(timezone.utc).replace(microsecond=0)
                overdue = now.replace(hour=max(0, now.hour - 2), minute=0, second=0)
                key = pipeline.store.upsert_content(
                    ExtractedContent(
                        source="news",
                        source_type="article",
                        source_item_id="4",
                        canonical_url="https://example.com/4",
                        title="El Gobierno anuncio una medida politica",
                        summary="El Congreso analizara el proyecto durante la jornada.",
                        media_type="image",
                        created_at=now.isoformat(),
                    )
                )
                pipeline.store.save_formatted(
                    key,
                    FormattedPackage(content_key=key, post_type="image", caption="Caption"),
                )
                pipeline.store.save_schedule(
                    key,
                    ScheduleDecision(
                        scheduled_for=overdue.isoformat(),
                        slot_label="12:00",
                        priority_rank=1,
                        reason="test",
                    ),
                )

                self.assertEqual(
                    pipeline.run_publisher(
                        safe_mode=False,
                        fixed_slot_only=True,
                        active_slot_override="18:00",
                    ),
                    1,
                )

                row = pipeline.store.find_content(key)
                assert row is not None
                self.assertEqual(row["pipeline_status"], "published")
                self.assertEqual(fake_publisher.instagram_calls, 1)
                self.assertEqual(fake_publisher.facebook_calls, 1)

    def test_publish_cap_is_never_larger_than_one_block(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DUO_SCHEDULE_VIDEOS_PER_SLOT": "5",
                "DUO_SCHEDULE_POSTS_PER_SLOT": "10",
                "DUO_PUBLISH_DEFAULT_MAX_POSTS": "15",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            pipeline = DuoPipeline(get_settings())
            self.assertEqual(pipeline._resolve_publish_cap(max_posts=999, safe_mode=False), 15)

    def test_publish_block_respects_five_videos_and_ten_posts(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DUO_SCHEDULE_VIDEOS_PER_SLOT": "5",
                "DUO_SCHEDULE_POSTS_PER_SLOT": "10",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            pipeline = DuoPipeline(get_settings())
            rows = [
                {"content_key": f"video-{index}", "assigned_post_type": "reel"}
                for index in range(8)
            ]
            rows.extend(
                {"content_key": f"post-{index}", "assigned_post_type": "carousel"}
                for index in range(12)
            )

            selected = pipeline._select_publish_block(rows, cap=999)

            self.assertEqual(len(selected), 15)
            self.assertEqual(sum(1 for row in selected if str(row["content_key"]).startswith("video-")), 5)
            self.assertEqual(sum(1 for row in selected if str(row["content_key"]).startswith("post-")), 10)

    def test_publish_block_interleaves_videos_and_posts_when_possible(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DUO_SCHEDULE_VIDEOS_PER_SLOT": "3",
                "DUO_SCHEDULE_POSTS_PER_SLOT": "3",
                "DUO_PUBLISH_MAX_PER_SOURCE_PER_BLOCK": "2",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            pipeline = DuoPipeline(get_settings())
            rows = [
                {"content_key": "video-1", "assigned_post_type": "reel", "source_handle": "a"},
                {"content_key": "video-2", "assigned_post_type": "reel", "source_handle": "a"},
                {"content_key": "video-3", "assigned_post_type": "reel", "source_handle": "b"},
                {"content_key": "post-1", "assigned_post_type": "image", "source": "tn"},
                {"content_key": "post-2", "assigned_post_type": "image", "source": "tn"},
                {"content_key": "post-3", "assigned_post_type": "image", "source": "infobae"},
            ]

            selected = pipeline._select_publish_block(rows, cap=6)
            ordered = [str(row["content_key"]) for row in selected]

            self.assertEqual(
                ordered,
                ["video-1", "post-1", "video-3", "post-3", "video-2", "post-2"],
            )

    def test_publish_block_prefers_more_sources_before_repeating_one(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DUO_SCHEDULE_VIDEOS_PER_SLOT": "0",
                "DUO_SCHEDULE_POSTS_PER_SLOT": "5",
                "DUO_PUBLISH_MAX_PER_SOURCE_PER_BLOCK": "2",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            pipeline = DuoPipeline(get_settings())
            rows = [
                {"content_key": "tn-1", "assigned_post_type": "image", "source": "tn"},
                {"content_key": "tn-2", "assigned_post_type": "image", "source": "tn"},
                {"content_key": "tn-3", "assigned_post_type": "image", "source": "tn"},
                {"content_key": "inf-1", "assigned_post_type": "image", "source": "infobae"},
                {"content_key": "amb-1", "assigned_post_type": "image", "source": "ambitofinanciero"},
            ]

            selected = pipeline._select_publish_block(rows, cap=5)
            ordered = [str(row["content_key"]) for row in selected]

            self.assertEqual(ordered[:4], ["tn-1", "inf-1", "amb-1", "tn-2"])

    def test_publish_block_prioritizes_salta_posts_over_national_posts(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DUO_SCHEDULE_VIDEOS_PER_SLOT": "0",
                "DUO_SCHEDULE_POSTS_PER_SLOT": "3",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            pipeline = DuoPipeline(get_settings())
            rows = [
                {"content_key": "tn-1", "assigned_post_type": "image", "source": "tn", "assigned_time": "2026-04-05T21:00:00+00:00"},
                {"content_key": "salta-1", "assigned_post_type": "image", "source": "eltribuno", "assigned_time": "2026-04-05T21:00:00+00:00"},
                {"content_key": "inf-1", "assigned_post_type": "image", "source": "infobae", "assigned_time": "2026-04-05T21:00:00+00:00"},
            ]

            selected = pipeline._select_publish_block(rows, cap=3)

        self.assertEqual(str(selected[0]["content_key"]), "salta-1")

    def test_publish_platform_records_defers_cleanup_until_batch_end(self) -> None:
        pipeline = DuoPipeline(get_settings())
        fake_publisher = CleanupAwarePublisher()
        pipeline.publisher = fake_publisher  # type: ignore[assignment]
        package = FormattedPackage(
            content_key="abc",
            post_type="image",
            caption="Caption",
            assets=[Asset(kind="image", path="C:/tmp/test.jpg")],
        )

        records = pipeline._publish_platform_records(
            package,
            scheduled_for="2026-04-07T09:00:00+00:00",
            platforms=["instagram", "facebook"],
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(fake_publisher.defer_during_publish, [True, True])
        self.assertEqual(fake_publisher.cleanup_calls, 1)
        self.assertEqual(fake_publisher.defer_during_cleanup, [None])
        self.assertNotIn("defer_cleanup", package.meta)

    def test_top_up_slot_videos_rescrapes_x_when_block_is_under_target(self) -> None:
        with patch.dict(
            os.environ,
            {
                "X_MODE": "feed",
                "DUO_SCHEDULE_VIDEOS_PER_SLOT": "5",
                "DUO_X_DEFAULT_ITEMS_PER_HANDLE": "8",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            pipeline = DuoPipeline(get_settings())
            with patch.object(
                pipeline,
                "_count_due_slot_videos",
                side_effect=[2, 5],
            ), patch.object(
                pipeline.x_extractor,
                "extract",
                return_value=[],
            ) as mocked_extract, patch.object(
                pipeline,
                "_ingest_rows",
                return_value=3,
            ), patch.object(
                pipeline,
                "run_scoring",
                return_value=3,
            ), patch.object(
                pipeline,
                "run_editorial",
                return_value=3,
            ), patch.object(
                pipeline,
                "run_formatter",
                return_value=3,
            ), patch.object(
                pipeline,
                "run_scheduler",
                return_value=3,
            ):
                summary = pipeline._top_up_slot_videos(active_slot="21:00")

        self.assertEqual(summary, {"ingested": 3, "scored": 3, "editorialized": 3, "formatted": 3, "scheduled": 3})
        self.assertEqual(mocked_extract.call_count, 1)
        self.assertEqual(mocked_extract.call_args.kwargs["limit_per_handle"], 17)

    def test_run_pipeline_passes_cycle_slot_to_publisher(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_publish_") as tmp_dir:
            db_path = Path(tmp_dir) / "duo.sqlite3"
            with patch.dict(
                os.environ,
                {
                    "DUO_DB_PATH": str(db_path),
                    "DUO_LIVE_PUBLISH_ENABLED": "1",
                    "COMPUTERNAME": "FERNANDO",
                    "ENABLE_INSTAGRAM": "1",
                    "ENABLE_FACEBOOK": "1",
                },
                clear=False,
            ):
                get_settings.cache_clear()
                pipeline = SlotCapturingPipeline(get_settings())
                with patch.object(pipeline, "run_scraper", return_value=0), patch.object(
                    pipeline,
                    "run_scoring",
                    return_value=0,
                ), patch.object(
                    pipeline,
                    "run_editorial",
                    return_value=0,
                ), patch.object(
                    pipeline,
                    "run_formatter",
                    return_value=0,
                ), patch.object(
                    pipeline,
                    "run_scheduler",
                    return_value=0,
                ), patch.object(
                    pipeline,
                    "run_analytics",
                    return_value=0,
                ), patch.object(
                    pipeline,
                    "run_comment_engagement",
                    return_value=0,
                ), patch.object(
                    pipeline,
                    "_top_up_slot_videos",
                    return_value={"ingested": 0, "scored": 0, "editorialized": 0, "formatted": 0, "scheduled": 0},
                ), patch.object(
                    pipeline,
                    "_active_schedule_slot",
                    return_value="18:00",
                ):
                    pipeline.run_pipeline(dry_run=False, safe_mode=False, fixed_slot_publish=True)

        assert pipeline.run_publisher_kwargs is not None
        self.assertEqual(pipeline.run_publisher_kwargs.get("active_slot_override"), "18:00")


if __name__ == "__main__":
    unittest.main()
