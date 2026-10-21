"""Reel = video completo (tope 90 s), portada, fotos sin repetir y sin reels de foto animada."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from formatter.service import AssetFormatter, image_dhash
from storage.settings import get_settings
from utils.media_resolver import MediaResolver, VideoUnavailable, probe_video

FFMPEG = shutil.which("ffmpeg")


def make_video(path: Path, seconds: float, *, audio: bool = True, size: str = "320x568") -> Path:
    command = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=15:duration={seconds}"]
    if audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-shortest"]
    command += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(command, check=True, capture_output=True, timeout=120)
    return path


class PhotoDedupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="duo_photos_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        def scene(seed: int) -> np.ndarray:
            rng = np.random.default_rng(seed)
            image = np.zeros((360, 640, 3), np.uint8)
            for _ in range(12):
                x, y = int(rng.integers(0, 600)), int(rng.integers(0, 330))
                color = tuple(int(c) for c in rng.integers(0, 255, 3))
                cv2.rectangle(image, (x, y), (x + int(rng.integers(40, 200)), y + int(rng.integers(30, 160))), color, -1)
            return image

        base = scene(7)
        cv2.imwrite(str(self.tmp / "a.jpg"), base)
        # La misma foto en otro tamano y formato (lo que mandaba El Tribuno como webp + jpg).
        cv2.imwrite(str(self.tmp / "a_small.png"), cv2.resize(base, (320, 180), interpolation=cv2.INTER_AREA))
        cv2.imwrite(str(self.tmp / "b.jpg"), scene(11))

    def test_same_photo_in_other_format_is_dropped(self) -> None:
        formatter = AssetFormatter.__new__(AssetFormatter)
        paths = [str(self.tmp / "a.jpg"), str(self.tmp / "a_small.png"), str(self.tmp / "b.jpg")]
        unique = formatter._usable_photos("k", paths, row={"source": "informatesalta"})
        self.assertEqual(unique, [paths[0], paths[2]])

    def test_same_photo_with_other_crop_is_dropped(self) -> None:
        base = cv2.imread(str(self.tmp / "a.jpg"))
        noise = (np.random.default_rng(3).random(base.shape) * 60).astype(np.uint8)
        textured = cv2.add(base, noise)
        cv2.imwrite(str(self.tmp / "t.jpg"), textured)
        cv2.imwrite(str(self.tmp / "t_crop.jpg"), textured[20:330, :])  # 16:9 del mismo original
        formatter = AssetFormatter.__new__(AssetFormatter)
        paths = [str(self.tmp / "t.jpg"), str(self.tmp / "t_crop.jpg"), str(self.tmp / "b.jpg")]
        self.assertEqual(formatter._usable_photos("k", paths, row={"source": "informatesalta"}), [paths[0], paths[2]])

    def test_dhash_is_stable_across_sizes(self) -> None:
        a = image_dhash(str(self.tmp / "a.jpg"))
        b = image_dhash(str(self.tmp / "a_small.png"))
        self.assertLessEqual(bin(a ^ b).count("1"), 6)


@unittest.skipUnless(FFMPEG, "ffmpeg no instalado")
class VideoPieceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="duo_pieces_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.env = patch.dict(
            os.environ,
            {"DUO_FORMATTED_VIDEO_DIR": str(self.tmp / "reels"), "DUO_FORMATTED_IMAGE_DIR": str(self.tmp / "images")},
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)
        self.formatter = AssetFormatter(get_settings())

    def _row(self, source: Path, duration: float, *, src: str = "informatesalta") -> dict:
        return {
            "content_key": f"k{int(duration)}",
            "source": src,
            "title": "Titulo",
            "editorial_json": json.dumps({"caption": "Caption canonico", "overlay": "Overlay"}),
            "assets_json": json.dumps([{"kind": "video", "remote_url": "https://example.test/v.mp4"}]),
            "media_json": json.dumps({"video": {"path": str(source), "duration_seconds": duration, "kind": "mp4"}}),
        }

    def _legacy_render(self, segment, output, **kwargs):
        shutil.copy(segment, output)
        return str(output)

    def test_40_second_video_is_one_reel(self) -> None:
        source = make_video(self.tmp / "v40.mp4", 40)
        with patch("formatter.service.process_video_for_instagram", side_effect=self._legacy_render):
            package = self.formatter.format_row(self._row(source, 40.0))
        self.assertEqual(package.post_type, "reel")
        self.assertEqual(len(package.assets), 1)
        self.assertEqual(package.caption, "Caption canonico")
        self.assertTrue(package.thumbnail_path and Path(package.thumbnail_path).exists())

    def test_90_second_video_is_one_whole_reel(self) -> None:
        source = make_video(self.tmp / "v90.mp4", 90, size="160x284")
        with patch("formatter.service.process_video_for_instagram", side_effect=self._legacy_render):
            package = self.formatter.format_row(self._row(source, 90.0))
        self.assertEqual(package.post_type, "reel")
        self.assertEqual([a.kind for a in package.assets], ["video"])
        self.assertAlmostEqual(probe_video(package.assets[0].path)["duration"], 90.0, delta=0.6)
        self.assertNotIn("clips", package.meta)

    def test_video_longer_than_90_seconds_is_not_used(self) -> None:
        source = make_video(self.tmp / "v120.mp4", 120, size="160x284")
        with patch("formatter.service.process_video_for_instagram", side_effect=self._legacy_render):
            with self.assertRaisesRegex(RuntimeError, "supera el tope"):
                self.formatter.format_row(self._row(source, 120.0))

    def test_article_without_video_never_becomes_a_reel(self) -> None:
        row = {
            "content_key": "img1",
            "source": "eltribuno",
            "title": "Titulo",
            "editorial_json": json.dumps({"caption": "C"}),
            "assets_json": json.dumps([{"kind": "image", "path": __file__}]),
        }
        with patch.object(self.formatter, "_format_image", return_value="estatico") as static, patch.object(self.formatter, "_validate_package"):
            self.assertEqual(self.formatter.format_row(row), "estatico")
        static.assert_called_once()

    def test_paparazzi_without_video_is_rejected(self) -> None:
        row = {
            "content_key": "pap1",
            "source": "paparazzi",
            "title": "Titulo",
            "editorial_json": json.dumps({"caption": "C"}),
            "assets_json": json.dumps([{"kind": "image", "path": __file__}]),
        }
        with self.assertRaisesRegex(RuntimeError, "exige video real"):
            self.formatter.format_row(row)


@unittest.skipUnless(FFMPEG, "ffmpeg no instalado")
class MediaResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="duo_media_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.resolver = MediaResolver(self.tmp / "cache", min_seconds=5)

    def test_short_preview_is_not_the_article_video(self) -> None:
        source = make_video(self.tmp / "teaser.mp4", 2)
        with patch.object(self.resolver, "_download_mp4", side_effect=lambda url, target: shutil.copy(source, target)):
            with self.assertRaises(VideoUnavailable) as ctx:
                self.resolver.resolve("https://example.test/teaser.mp4", "mp4")
        self.assertEqual(ctx.exception.reason, "too_short")
        # El resultado queda en cache: el proximo ciclo no lo vuelve a bajar.
        with patch.object(self.resolver, "_download_mp4") as again:
            with self.assertRaises(VideoUnavailable):
                self.resolver.resolve("https://example.test/teaser.mp4", "mp4")
            again.assert_not_called()

    def test_download_failure_reports_reason(self) -> None:
        def fail(url, target):
            raise VideoUnavailable("download_failed", "HTTP 404")

        with patch.object(self.resolver, "_download_mp4", side_effect=fail):
            with self.assertRaises(VideoUnavailable) as ctx:
                self.resolver.resolve("https://example.test/missing.mp4", "mp4")
        self.assertEqual(ctx.exception.reason, "download_failed")

    def test_unsupported_format_is_rejected(self) -> None:
        bogus = self.tmp / "bogus.mp4"
        bogus.write_bytes(b"<html>no es un video</html>" * 50)
        with patch.object(self.resolver, "_download_mp4", side_effect=lambda url, target: shutil.copy(bogus, target)):
            with self.assertRaises(VideoUnavailable) as ctx:
                self.resolver.resolve("https://example.test/bogus.mp4", "mp4")
        self.assertEqual(ctx.exception.reason, "unsupported_format")

    def test_video_longer_than_reel_limit_is_rejected_and_cached(self) -> None:
        source = make_video(self.tmp / "long.mp4", 95, size="160x284")
        with patch.object(self.resolver, "_download_mp4", side_effect=lambda url, target: shutil.copy(source, target)):
            with self.assertRaises(VideoUnavailable) as ctx:
                self.resolver.resolve("https://example.test/long.mp4", "mp4")
        self.assertEqual(ctx.exception.reason, "too_long")
        with patch.object(self.resolver, "_download_mp4") as again:
            with self.assertRaises(VideoUnavailable):
                self.resolver.resolve("https://example.test/long.mp4", "mp4")
            again.assert_not_called()

    def test_declared_long_duration_skips_download(self) -> None:
        from storage.models import Asset

        asset = Asset(kind="video", remote_url="https://example.test/v.mp4", duration_seconds=224.0, meta={"video_kind": "mp4"})
        with patch.object(self.resolver, "_download_mp4") as download:
            with self.assertRaises(VideoUnavailable) as ctx:
                self.resolver.resolve_asset(asset)
        self.assertEqual(ctx.exception.reason, "too_long")
        download.assert_not_called()

    def test_long_video_is_trimmed_to_first_seconds_when_enabled(self) -> None:
        resolver = MediaResolver(self.tmp / "cache_trim", min_seconds=5, max_seconds=10, trim_long=True)
        source = make_video(self.tmp / "long_trim.mp4", 16, size="160x284")
        with patch.object(resolver, "_download_mp4", side_effect=lambda url, target: shutil.copy(source, target)) as download:
            first = resolver.resolve("https://example.test/long_trim.mp4", "mp4")
            second = resolver.resolve("https://example.test/long_trim.mp4", "mp4")
        self.assertTrue(first.trimmed)
        self.assertLessEqual(first.duration_seconds, 10.5)
        self.assertGreaterEqual(first.duration_seconds, 9.0)
        self.assertTrue(Path(first.path).is_relative_to(self.tmp / "cache_trim"))
        # La cache guarda el tramo recortado: el segundo ciclo no vuelve a bajar ni a recortar.
        self.assertEqual(download.call_count, 1)
        self.assertTrue(second.cache_hit)
        self.assertFalse(second.trimmed)

    def test_declared_long_duration_is_downloaded_when_trimming(self) -> None:
        from storage.models import Asset

        resolver = MediaResolver(self.tmp / "cache_trim2", min_seconds=5, max_seconds=10, trim_long=True)
        source = make_video(self.tmp / "declared.mp4", 14, size="160x284")
        asset = Asset(kind="video", remote_url="https://example.test/d.mp4", duration_seconds=224.0, meta={"video_kind": "mp4"})
        with patch.object(resolver, "_download_mp4", side_effect=lambda url, target: shutil.copy(source, target)):
            resolved = resolver.resolve_asset(asset)
        self.assertTrue(resolved.trimmed)
        self.assertLessEqual(resolved.duration_seconds, 10.5)

    def test_cached_too_long_is_retried_when_trimming(self) -> None:
        source = make_video(self.tmp / "retry.mp4", 14, size="160x284")
        with patch.object(MediaResolver, "_download_mp4", side_effect=lambda url, target: shutil.copy(source, target)):
            strict = MediaResolver(self.tmp / "cache_retry", min_seconds=5, max_seconds=10)
            with self.assertRaises(VideoUnavailable):
                strict.resolve("https://example.test/retry.mp4", "mp4")
            trimming = MediaResolver(self.tmp / "cache_retry", min_seconds=5, max_seconds=10, trim_long=True)
            self.assertTrue(trimming.resolve("https://example.test/retry.mp4", "mp4").trimmed)

    def test_valid_video_is_cached(self) -> None:
        source = make_video(self.tmp / "ok.mp4", 8)
        with patch.object(self.resolver, "_download_mp4", side_effect=lambda url, target: shutil.copy(source, target)) as download:
            first = self.resolver.resolve("https://example.test/ok.mp4", "mp4")
            second = self.resolver.resolve("https://example.test/ok.mp4", "mp4")
        self.assertEqual(download.call_count, 1)
        self.assertTrue(second.cache_hit)
        self.assertAlmostEqual(first.duration_seconds, 8.0, delta=0.6)


if __name__ == "__main__":
    unittest.main()


class PlaceholderImageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="duo_placeholder_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_flat_logo_card_is_placeholder(self) -> None:
        from formatter.service import is_placeholder_image

        card = np.full((630, 1200, 3), (0, 140, 255), np.uint8)
        cv2.putText(card, "infobae", (250, 360), cv2.FONT_HERSHEY_SIMPLEX, 6, (255, 255, 255), 18)
        cv2.imwrite(str(self.tmp / "card.png"), card)
        self.assertTrue(is_placeholder_image(str(self.tmp / "card.png")))

    def test_real_scene_is_not_placeholder(self) -> None:
        from formatter.service import is_placeholder_image

        rng = np.random.default_rng(3)
        scene = cv2.GaussianBlur((rng.random((400, 600, 3)) * 255).astype(np.uint8), (9, 9), 0)
        cv2.imwrite(str(self.tmp / "scene.jpg"), scene)
        self.assertFalse(is_placeholder_image(str(self.tmp / "scene.jpg")))

    def test_placeholder_urls(self) -> None:
        from formatter.service import is_placeholder_image

        self.assertTrue(is_placeholder_image("", "https://www.infobae.com/assets/images/logos/fallback-promo-image-1200x630.png"))
        self.assertFalse(is_placeholder_image("", "https://cdn.example.com/2026/10/catalogo-de-ofertas.jpg"))
