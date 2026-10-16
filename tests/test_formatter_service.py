from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from formatter.service import AssetFormatter
from storage.models import Asset, FormattedPackage
from storage.settings import get_settings
from utils.image_processor import normalize_for_instagram_premium_v2_card


class FormatterServiceTests(unittest.TestCase):
    def test_video_formatter_uses_editorial_overlay_and_layout_template(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_formatter_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            with patch.dict(
                os.environ,
                {
                    "DUO_FORMATTED_VIDEO_DIR": str(tmp_path / "reels"),
                    "DUO_FORMATTED_IMAGE_DIR": str(tmp_path / "images"),
                },
            ):
                get_settings.cache_clear()
                formatter = AssetFormatter(get_settings())
                row = {
                    "content_key": "abc123",
                    "title": "Titulo de prueba",
                    "summary": "Resumen",
                    "media_type": "video",
                    "editorial_json": json.dumps({"caption": "Caption", "overlay": "Overlay", "hook": "Hook"}),
                    "assets_json": json.dumps(
                        [
                            {
                                "kind": "video",
                                "path": str(tmp_path / "source.mp4"),
                                "duration_seconds": 12.0,
                            }
                        ]
                    ),
                }
                def fake_process_video(*args: object, **kwargs: object) -> str:
                    output = tmp_path / "out.mp4"
                    output.write_bytes(b"0" * 60000)
                    return str(output)

                with patch("formatter.service.process_video_for_instagram", side_effect=fake_process_video) as mocked, patch.object(
                    AssetFormatter,
                    "_render_thumbnail",
                    return_value=str(tmp_path / "thumb.jpg"),
                ):
                    package = formatter.format_row(row)

        self.assertEqual(package.post_type, "reel")
        self.assertEqual(mocked.call_args.kwargs["title_text"], "Overlay")
        self.assertTrue(str(mocked.call_args.kwargs["template_path"]).endswith("hola_salta.json"))

    def test_news_item_with_unusable_video_falls_back_to_image(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_formatter_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            image_path = tmp_path / "formatted.jpg"
            image_path.write_bytes(b"0" * 4096)
            with patch.dict(
                os.environ,
                {
                    "DUO_FORMATTED_VIDEO_DIR": str(tmp_path / "reels"),
                    "DUO_FORMATTED_IMAGE_DIR": str(tmp_path / "images"),
                },
            ):
                get_settings.cache_clear()
                formatter = AssetFormatter(get_settings())
                row = {
                    "content_key": "abc123",
                    "source_type": "news",
                    "title": "Titulo de prueba",
                    "media_type": "video",
                    "editorial_json": json.dumps({"caption": "Caption", "overlay": "Overlay"}),
                    "assets_json": json.dumps(
                        [
                            {"kind": "image", "remote_url": "https://cdn.example.com/foto.jpg"},
                            {"kind": "video", "remote_url": ""},
                        ]
                    ),
                }
                fallback = FormattedPackage(
                    content_key="abc123",
                    post_type="image",
                    caption="Caption",
                    thumbnail_path=str(image_path),
                    assets=[Asset(kind="image", path=str(image_path))],
                    meta={"style": "legacy_image_formatter"},
                )
                with patch.object(AssetFormatter, "_format_image", return_value=fallback) as mocked_image:
                    package = formatter.format_row(row)

        self.assertEqual(package.post_type, "image")
        mocked_image.assert_called_once()

    def test_image_formatter_uses_premium_v2_layout_by_default(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_formatter_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "source.jpg"
            Image.new("RGB", (1200, 800), (80, 80, 120)).save(source_path)

            with patch.dict(
                os.environ,
                {
                    "DUO_FORMATTED_VIDEO_DIR": str(tmp_path / "reels"),
                    "DUO_FORMATTED_IMAGE_DIR": str(tmp_path / "images"),
                },
                clear=False,
            ):
                os.environ.pop("IG_IMAGE_LAYOUT_STYLE", None)
                get_settings.cache_clear()
                formatter = AssetFormatter(get_settings())
                row = {
                    "content_key": "abc123",
                    "source_type": "news",
                    "title": "Titulo de prueba",
                    "media_type": "image",
                    "editorial_json": json.dumps({"caption": "Caption", "overlay": "Overlay"}),
                    "assets_json": json.dumps([{"kind": "image", "path": str(source_path)}]),
                }

                def fake_premium_v2(*args: object, **kwargs: object) -> str:
                    output = tmp_path / "premium_v2.jpg"
                    output.write_bytes(b"1" * 4096)
                    return str(output)

                with patch("formatter.service.normalize_for_instagram_premium_v2_card", side_effect=fake_premium_v2) as premium_v2, patch(
                    "formatter.service.normalize_for_instagram_premium_card"
                ) as premium, patch(
                    "formatter.service.normalize_for_instagram_pink_card"
                ) as legacy:
                    package = formatter.format_row(row)

        self.assertEqual(package.post_type, "image")
        self.assertEqual(package.meta["style"], "premium_v2_image_formatter")
        self.assertIn(package.meta["visual_theme"], {"showbiz", "default"})
        premium_v2.assert_called_once()
        premium.assert_not_called()
        legacy.assert_not_called()

    def test_image_formatter_can_use_premium_v1_layout_from_env(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_formatter_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "source.jpg"
            Image.new("RGB", (1200, 800), (80, 80, 120)).save(source_path)

            with patch.dict(
                os.environ,
                {
                    "DUO_FORMATTED_VIDEO_DIR": str(tmp_path / "reels"),
                    "DUO_FORMATTED_IMAGE_DIR": str(tmp_path / "images"),
                    "IG_IMAGE_LAYOUT_STYLE": "premium",
                },
            ):
                get_settings.cache_clear()
                formatter = AssetFormatter(get_settings())
                row = {
                    "content_key": "abc123",
                    "source_type": "news",
                    "title": "Titulo de prueba",
                    "media_type": "image",
                    "editorial_json": json.dumps({"caption": "Caption", "overlay": "Overlay"}),
                    "assets_json": json.dumps([{"kind": "image", "path": str(source_path)}]),
                }

                def fake_premium(*args: object, **kwargs: object) -> str:
                    output = tmp_path / "premium.jpg"
                    output.write_bytes(b"1" * 4096)
                    return str(output)

                with patch("formatter.service.normalize_for_instagram_premium_card", side_effect=fake_premium) as premium, patch(
                    "formatter.service.normalize_for_instagram_premium_v2_card"
                ) as premium_v2, patch("formatter.service.normalize_for_instagram_pink_card") as legacy:
                    package = formatter.format_row(row)

        self.assertEqual(package.post_type, "image")
        self.assertEqual(package.meta["style"], "premium_image_formatter")
        premium.assert_called_once()
        premium_v2.assert_not_called()
        legacy.assert_not_called()

    def test_image_formatter_can_use_legacy_layout_from_env(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_formatter_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "source.jpg"
            Image.new("RGB", (1200, 800), (80, 80, 120)).save(source_path)

            with patch.dict(
                os.environ,
                {
                    "DUO_FORMATTED_VIDEO_DIR": str(tmp_path / "reels"),
                    "DUO_FORMATTED_IMAGE_DIR": str(tmp_path / "images"),
                    "IG_IMAGE_LAYOUT_STYLE": "legacy",
                },
            ):
                get_settings.cache_clear()
                formatter = AssetFormatter(get_settings())
                row = {
                    "content_key": "abc123",
                    "source_type": "news",
                    "title": "Titulo de prueba",
                    "media_type": "image",
                    "editorial_json": json.dumps({"caption": "Caption", "overlay": "Overlay"}),
                    "assets_json": json.dumps([{"kind": "image", "path": str(source_path)}]),
                }

                def fake_legacy(*args: object, **kwargs: object) -> str:
                    output = tmp_path / "legacy.jpg"
                    output.write_bytes(b"1" * 4096)
                    return str(output)

                with patch("formatter.service.normalize_for_instagram_pink_card", side_effect=fake_legacy) as legacy, patch(
                    "formatter.service.normalize_for_instagram_premium_v2_card"
                ) as premium_v2, patch(
                    "formatter.service.normalize_for_instagram_premium_card"
                ) as premium:
                    package = formatter.format_row(row)

        self.assertEqual(package.post_type, "image")
        self.assertEqual(package.meta["style"], "legacy_image_formatter")
        legacy.assert_called_once()
        premium_v2.assert_not_called()
        premium.assert_not_called()

    def test_premium_v2_card_renders_long_title(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_premium_card_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_path = tmp_path / "source.jpg"
            Image.new("RGB", (1400, 780), (60, 90, 130)).save(source_path)
            output = normalize_for_instagram_premium_v2_card(
                str(source_path),
                output_filename="premium_v2.jpg",
                folder=str(tmp_path),
                title_text="Un titulo largo de prueba para verificar que el nuevo layout premium no se rompa",
                kicker_text="PREVIEW",
                content_theme="showbiz",
                title_font_path=str(Path(__file__).resolve().parents[1] / "media" / "Montserrat-ExtraBold.ttf"),
            )

            self.assertIsNotNone(output)
            self.assertTrue(Path(str(output)).exists())
            self.assertGreater(Path(str(output)).stat().st_size, 2048)

    def test_missing_remote_image_creates_fallback_source_image(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_formatter_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            with patch.dict(
                os.environ,
                {
                    "DUO_FORMATTED_VIDEO_DIR": str(tmp_path / "reels"),
                    "DUO_FORMATTED_IMAGE_DIR": str(tmp_path / "images"),
                },
            ):
                get_settings.cache_clear()
                formatter = AssetFormatter(get_settings())
                formatter.temp_dir = tmp_path / "tmp"
                with patch("formatter.service.process_image", return_value=None):
                    local = formatter._ensure_local_image(
                        Asset(kind="image", remote_url="https://cdn.example.com/blocked.jpg"),
                        "abc123",
                        0,
                        row={},
                        raw_payload={},
                    )

                self.assertTrue(Path(local).exists())
                self.assertGreater(Path(local).stat().st_size, 2048)

    def test_missing_remote_image_uses_article_candidate_before_fallback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_formatter_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            resolved = tmp_path / "resolved.jpg"
            resolved.write_bytes(b"1" * 4096)
            with patch.dict(
                os.environ,
                {
                    "DUO_FORMATTED_VIDEO_DIR": str(tmp_path / "reels"),
                    "DUO_FORMATTED_IMAGE_DIR": str(tmp_path / "images"),
                },
            ):
                get_settings.cache_clear()
                formatter = AssetFormatter(get_settings())
                formatter.temp_dir = tmp_path / "tmp"
                with patch(
                    "formatter.service.process_image",
                    side_effect=[None, str(resolved)],
                ) as mocked, patch.object(
                    formatter,
                    "_discover_article_image_candidates",
                    return_value=["https://cdn.example.com/foto.jpg?auth=abc123"],
                ):
                    local = formatter._ensure_local_image(
                        Asset(kind="image", remote_url="https://cdn.example.com/foto.jpg"),
                        "abc123",
                        0,
                        row={"canonical_url": "https://example.com/nota", "source_type": "news"},
                        raw_payload={},
                    )

                self.assertEqual(local, str(resolved))
                self.assertEqual(mocked.call_count, 2)

    def test_missing_remote_image_raises_for_article_when_no_real_image_is_available(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_formatter_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            with patch.dict(
                os.environ,
                {
                    "DUO_FORMATTED_VIDEO_DIR": str(tmp_path / "reels"),
                    "DUO_FORMATTED_IMAGE_DIR": str(tmp_path / "images"),
                },
            ):
                get_settings.cache_clear()
                formatter = AssetFormatter(get_settings())
                with patch("formatter.service.process_image", return_value=None), patch.object(
                    formatter,
                    "_discover_article_image_candidates",
                    return_value=[],
                ):
                    with self.assertRaisesRegex(RuntimeError, "no pudo descargar imagen fuente real"):
                        formatter._ensure_local_image(
                            Asset(kind="image", remote_url="https://cdn.example.com/blocked.jpg"),
                            "abc123",
                            0,
                            row={"canonical_url": "https://example.com/nota", "source_type": "news"},
                            raw_payload={},
                        )


if __name__ == "__main__":
    unittest.main()
