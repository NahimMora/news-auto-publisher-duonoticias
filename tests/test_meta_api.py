from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from publishers.meta_api import MetaGraphPublisher
from storage.models import Asset, FormattedPackage
from storage.settings import get_settings


class MetaGraphPublisherTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_settings.cache_clear()

    def test_fb_page_account_uses_me_accounts_page_token(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FB_ACCESS_TOKEN": "user-token",
                "FB_PAGE_ID": "",
                "IG_ACCESS_TOKEN": "",
                "IG_USER_ID": "",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            publisher = MetaGraphPublisher(get_settings())
            with patch.object(
                publisher,
                "_request",
                return_value={
                    "data": [
                        {
                            "id": "883117364894236",
                            "name": "Dúo Noticias",
                            "access_token": "page-token",
                            "tasks": ["CREATE_CONTENT"],
                        }
                    ]
                },
            ) as request_mock:
                self.assertEqual(publisher._get_fb_page_id(), "883117364894236")
                self.assertEqual(publisher._get_fb_publish_token(), "page-token")
                request_mock.assert_called_once()

    def test_fb_page_account_failure_returns_empty_values(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FB_ACCESS_TOKEN": "user-token",
                "FB_PAGE_ID": "",
                "IG_ACCESS_TOKEN": "",
                "IG_USER_ID": "",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            publisher = MetaGraphPublisher(get_settings())
            with patch.object(publisher, "_request", side_effect=RuntimeError("boom")):
                self.assertEqual(publisher._get_fb_page_id(), "")
                self.assertEqual(publisher._get_fb_page_account(), {})
                self.assertEqual(publisher._get_fb_publish_token(), "user-token")

    def test_instagram_reel_uses_resumable_upload_for_local_video(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_meta_") as tmp_dir, patch.dict(
            os.environ,
            {
                "IG_ACCESS_TOKEN": "ig-token",
                "IG_USER_ID": "ig-user",
                "IG_REELS_UPLOAD_MODE": "resumable",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            video_path = Path(tmp_dir) / "reel.mp4"
            video_path.write_bytes(b"0" * 1024)
            publisher = MetaGraphPublisher(get_settings())
            package = FormattedPackage(
                content_key="abc",
                post_type="reel",
                caption="caption",
                assets=[Asset(kind="video", path=str(video_path))],
                meta={"skip_cloud_cleanup": True},
            )
            with patch.object(
                publisher,
                "_create_reel_resumable_container",
                return_value=("container-id", "https://rupload.example/container-id"),
            ) as create_mock, patch.object(
                publisher,
                "_upload_resumable_video",
                return_value={"success": True},
            ) as upload_mock, patch.object(
                publisher,
                "_wait_container",
            ) as wait_mock, patch.object(
                publisher,
                "_publish_container",
                return_value="media-id",
            ), patch.object(
                publisher,
                "_asset_media_url",
                side_effect=AssertionError("standard URL upload should not be used"),
            ):
                self.assertEqual(publisher._publish_instagram(package), "media-id")

        create_mock.assert_called_once_with("caption")
        upload_mock.assert_called_once()
        wait_mock.assert_called_once_with("container-id")

    def test_instagram_reel_falls_back_to_url_container_when_resumable_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_meta_") as tmp_dir, patch.dict(
            os.environ,
            {
                "IG_ACCESS_TOKEN": "ig-token",
                "IG_USER_ID": "ig-user",
                "IG_REELS_UPLOAD_MODE": "resumable",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            video_path = Path(tmp_dir) / "reel.mp4"
            video_path.write_bytes(b"0" * 1024)
            publisher = MetaGraphPublisher(get_settings())
            package = FormattedPackage(
                content_key="abc",
                post_type="reel",
                caption="caption",
                assets=[Asset(kind="video", path=str(video_path))],
                meta={"skip_cloud_cleanup": True},
            )
            with patch.object(
                publisher,
                "_create_reel_resumable_container",
                return_value=("container-id", "https://rupload.example/container-id"),
            ) as create_mock, patch.object(
                publisher,
                "_upload_resumable_video",
                side_effect=RuntimeError("boom"),
            ) as upload_mock, patch.object(
                publisher,
                "_create_reel_url_container",
                return_value="url-container-id",
            ) as url_mock, patch.object(
                publisher,
                "_wait_container",
            ) as wait_mock, patch.object(
                publisher,
                "_publish_container",
                return_value="media-id",
            ):
                self.assertEqual(publisher._publish_instagram(package), "media-id")

        create_mock.assert_called_once_with("caption")
        upload_mock.assert_called_once()
        url_mock.assert_called_once()
        wait_mock.assert_called_once_with("url-container-id")

    def test_publish_instagram_defers_cleanup_when_requested(self) -> None:
        with patch.dict(
            os.environ,
            {
                "IG_ACCESS_TOKEN": "ig-token",
                "IG_USER_ID": "ig-user",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            publisher = MetaGraphPublisher(get_settings())
            package = FormattedPackage(
                content_key="abc",
                post_type="image",
                caption="caption",
                assets=[Asset(kind="image", path="C:/tmp/test.jpg")],
                meta={"defer_cleanup": True},
            )
            with patch.object(publisher, "_has_permission", return_value=True), patch.object(
                publisher,
                "get_ig_publish_limit",
                return_value={"remaining": 25},
            ), patch.object(
                publisher,
                "_publish_instagram",
                return_value="media-id",
            ), patch.object(
                publisher,
                "_get_instagram_permalink",
                return_value="https://instagram.com/p/test",
            ), patch.object(
                publisher,
                "_cleanup_assets",
            ) as cleanup_mock:
                record = publisher.publish_instagram(package)

        self.assertEqual(record.status, "published")
        cleanup_mock.assert_not_called()

    def test_cleanup_package_assets_uses_all_local_paths(self) -> None:
        publisher = MetaGraphPublisher(get_settings())
        package = FormattedPackage(
            content_key="abc",
            post_type="carousel",
            caption="caption",
            assets=[
                Asset(kind="image", path="C:/tmp/a.jpg"),
                Asset(kind="video", path="C:/tmp/b.mp4"),
                Asset(kind="image", path=""),
            ],
        )
        with patch.object(publisher, "_cleanup_assets") as cleanup_mock:
            publisher.cleanup_package_assets(package)

        cleanup_mock.assert_called_once_with(
            package,
            ["C:/tmp/a.jpg", "C:/tmp/b.mp4"],
        )

    def test_collect_instagram_metrics_uses_supported_metric_list(self) -> None:
        with patch.dict(
            os.environ,
            {
                "IG_ACCESS_TOKEN": "ig-token",
                "IG_USER_ID": "ig-user",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            publisher = MetaGraphPublisher(get_settings())
            requested_metrics: list[str] = []

            def request_side_effect(method, path, *, params=None, data=None, access_token):
                if path == "/media-id":
                    return {
                        "id": "media-id",
                        "caption": "caption",
                        "comments_count": 1,
                        "like_count": 2,
                        "media_product_type": "FEED",
                        "media_type": "IMAGE",
                        "permalink": "https://instagram.com/p/test",
                        "timestamp": "2026-05-04T00:00:00+0000",
                    }
                if path == "/media-id/insights":
                    requested_metrics.append(str((params or {}).get("metric") or ""))
                    return {"data": []}
                raise AssertionError(f"unexpected path: {path}")

            with patch.object(publisher, "_has_permission", return_value=True), patch.object(
                publisher,
                "_request",
                side_effect=request_side_effect,
            ):
                publisher.collect_instagram_metrics("media-id")

        self.assertEqual(
            requested_metrics,
            ["reach", "saved", "shares", "views", "total_interactions", "likes", "comments"],
        )

    def test_collect_instagram_metrics_uses_resolved_media_id_for_insights(self) -> None:
        with patch.dict(
            os.environ,
            {
                "IG_ACCESS_TOKEN": "ig-token",
                "IG_USER_ID": "ig-user",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            publisher = MetaGraphPublisher(get_settings())
            insight_paths: list[str] = []

            def request_side_effect(method, path, *, params=None, data=None, access_token):
                if path == "/bad-id":
                    raise RuntimeError("not found")
                if path == "/good-id":
                    return {
                        "id": "good-id",
                        "caption": "caption",
                        "comments_count": 1,
                        "like_count": 2,
                        "media_product_type": "REELS",
                        "media_type": "VIDEO",
                        "permalink": "https://instagram.com/reel/test",
                        "timestamp": "2026-05-04T00:00:00+0000",
                    }
                if path == "/good-id/insights":
                    insight_paths.append(path)
                    return {"data": []}
                raise AssertionError(f"unexpected path: {path}")

            with patch.object(publisher, "_has_permission", return_value=True), patch.object(
                publisher,
                "_resolve_instagram_media_id",
                return_value="good-id",
            ), patch.object(
                publisher,
                "_request",
                side_effect=request_side_effect,
            ):
                metrics = publisher.collect_instagram_metrics(
                    "bad-id",
                    permalink="https://instagram.com/reel/test",
                    published_at="2026-05-04T00:00:00+0000",
                )

        self.assertEqual((metrics.get("meta") or {}).get("resolved_media_id"), "good-id")
        self.assertTrue(insight_paths)
        self.assertTrue(all(path == "/good-id/insights" for path in insight_paths))

    def test_collect_facebook_metrics_uses_supported_fields(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FB_ACCESS_TOKEN": "fb-token",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            publisher = MetaGraphPublisher(get_settings())
            seen_fields: list[str] = []

            def request_side_effect(method, path, *, params=None, data=None, access_token):
                seen_fields.append(str((params or {}).get("fields") or ""))
                return {"id": "post-id"}

            with patch.object(publisher, "_has_permission", return_value=True), patch.object(
                publisher,
                "_get_fb_publish_token",
                return_value="page-token",
            ), patch.object(
                publisher,
                "_request",
                side_effect=request_side_effect,
            ):
                publisher.collect_facebook_metrics("post-id")

        self.assertEqual(
            seen_fields,
            ["id,permalink_url,comments.limit(0).summary(true),likes.limit(0).summary(true)"],
        )


if __name__ == "__main__":
    unittest.main()
