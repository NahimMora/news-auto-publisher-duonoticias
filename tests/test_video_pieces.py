"""Recorte mecanico de video y armado de piezas (sin reels de foto animada)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from formatter.service import AssetFormatter
from storage.settings import get_settings
from utils.media_resolver import MediaResolver, VideoUnavailable, probe_video
from utils.video_clips import ClipSpec, cut_segment, plan_clips

FFMPEG = shutil.which("ffmpeg")


def make_video(path: Path, seconds: float, *, audio: bool = True, size: str = "320x568") -> Path:
    command = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=15:duration={seconds}"]
    if audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-shortest"]
    command += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(command, check=True, capture_output=True, timeout=120)
    return path


class ClipPlanTests(unittest.TestCase):
    def test_video_of_40_seconds_is_used_whole(self) -> None:
        self.assertEqual(plan_clips(40.0), [ClipSpec(0, 0.0, 40.0)])

    def test_video_of_90_seconds_gives_0_60_and_remaining(self) -> None:
        self.assertEqual(plan_clips(90.0), [ClipSpec(0, 0.0, 60.0), ClipSpec(1, 60.0, 30.0)])

    def test_long_video_uses_first_two_minutes_only(self) -> None:
        # 23 minutos: 00:00-01:00 y 01:00-02:00; nunca tramos del medio.
        self.assertEqual(plan_clips(23 * 60.0), [ClipSpec(0, 0.0, 60.0), ClipSpec(1, 60.0, 60.0)])

    def test_tiny_remainder_is_not_a_second_clip(self) -> None:
        self.assertEqual(plan_clips(62.0), [ClipSpec(0, 0.0, 60.0)])

    def test_no_duration_no_clips(self) -> None:
        self.assertEqual(plan_clips(0), [])


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

    def test_cut_segment_is_exact(self) -> None:
        source = make_video(self.tmp / "v90.mp4", 90)
        out = cut_segment(str(source), str(self.tmp / "c2.mp4"), ClipSpec(1, 60.0, 30.0))
        self.assertAlmostEqual(probe_video(out)["duration"], 30.0, delta=0.6)

    def test_40_second_video_is_one_reel(self) -> None:
        source = make_video(self.tmp / "v40.mp4", 40)
        with patch("formatter.service.process_video_for_instagram", side_effect=self._legacy_render):
            package = self.formatter.format_row(self._row(source, 40.0))
        self.assertEqual(package.post_type, "reel")
        self.assertEqual(len(package.assets), 1)
        self.assertEqual(package.caption, "Caption canonico")

    def test_90_second_video_is_two_clip_carousel(self) -> None:
        source = make_video(self.tmp / "v90.mp4", 90)
        with patch("formatter.service.process_video_for_instagram", side_effect=self._legacy_render):
            package = self.formatter.format_row(self._row(source, 90.0))
        self.assertEqual(package.post_type, "carousel")
        self.assertEqual([a.kind for a in package.assets], ["video", "video"])
        durations = [probe_video(a.path)["duration"] for a in package.assets]
        self.assertAlmostEqual(durations[0], 60.0, delta=0.6)
        self.assertAlmostEqual(durations[1], 30.0, delta=0.6)
        self.assertEqual(package.meta["clips"], [{"start": 0.0, "end": 60.0}, {"start": 60.0, "end": 90.0}])
        self.assertEqual(package.meta["facebook_video_index"], 0)

    def test_several_minutes_video_uses_0_60_and_60_120(self) -> None:
        source = make_video(self.tmp / "v200.mp4", 200, size="160x284")
        with patch("formatter.service.process_video_for_instagram", side_effect=self._legacy_render):
            package = self.formatter.format_row(self._row(source, 200.0))
        self.assertEqual(package.meta["clips"], [{"start": 0.0, "end": 60.0}, {"start": 60.0, "end": 120.0}])

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
