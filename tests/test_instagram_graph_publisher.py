from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import utils.instagram_graph_publisher as legacy_ig


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def post(self, *_args, **_kwargs) -> _FakeResponse:
        return _FakeResponse(self._payload)

    def close(self) -> None:
        return None


class InstagramGraphPublisherTests(unittest.TestCase):
    def tearDown(self) -> None:
        legacy_ig._cloudinary_cache.clear()
        legacy_ig._media_storage_cache.clear()

    def test_cleanup_cloudinary_clears_cache_for_future_reupload(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_cloudinary_") as tmp_dir:
            local_path = Path(tmp_dir) / "image.jpg"
            local_path.write_bytes(b"abc")
            upload_side_effect = [
                {"url": "https://cloudinary.example/first", "public_id": "first", "resource_type": "image"},
                {"url": "https://cloudinary.example/second", "public_id": "second", "resource_type": "image"},
            ]
            with patch.object(legacy_ig, "CLOUDINARY_CLOUD_NAME", "cloud"), patch.object(
                legacy_ig,
                "CLOUDINARY_API_KEY",
                "key",
            ), patch.object(
                legacy_ig,
                "MEDIA_STORAGE_PROVIDER",
                "cloudinary",
            ), patch.object(
                legacy_ig,
                "CLOUDINARY_API_SECRET",
                "secret",
            ), patch.object(
                legacy_ig,
                "CLOUDINARY_DELETE_AFTER_PUBLISH",
                True,
            ), patch.object(
                legacy_ig,
                "_cloudinary_upload",
                side_effect=upload_side_effect,
            ) as upload_mock, patch.object(
                legacy_ig,
                "_new_http_client",
                return_value=_FakeClient({"result": "ok"}),
            ):
                first_url = legacy_ig._resolve_media_url(str(local_path))
                legacy_ig._cleanup_cloudinary([str(local_path)])
                second_url = legacy_ig._resolve_media_url(str(local_path))

        self.assertEqual(first_url, "https://cloudinary.example/first")
        self.assertEqual(second_url, "https://cloudinary.example/second")
        self.assertEqual(upload_mock.call_count, 2)

    def test_resolve_media_url_uploads_to_r2_temp_folder(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_r2_") as tmp_dir:
            local_path = Path(tmp_dir) / "image.jpg"
            local_path.write_bytes(b"abc")
            with patch.object(legacy_ig, "MEDIA_STORAGE_PROVIDER", "r2"), patch.object(
                legacy_ig.media_storage,
                "upload_file",
                return_value={
                    "provider": "r2",
                    "url": "https://media.example/img_temp/image.jpg",
                    "key": "img_temp/image.jpg",
                    "bucket": "duo",
                },
            ) as upload_mock:
                url = legacy_ig._resolve_media_url(str(local_path))

        self.assertEqual(url, "https://media.example/img_temp/image.jpg")
        upload_mock.assert_called_once_with(str(local_path), folder_kind="temp")
