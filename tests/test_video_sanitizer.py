from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.video_sanitizer import SanitizerConfig, sanitize_video


class VideoSanitizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="sanitizer_test_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _ffmpeg_bin(self) -> str:
        return "ffmpeg"

    def _create_synthetic_video(self, output_path: Path) -> None:
        ffmpeg = self._ffmpeg_bin()
        if shutil.which(ffmpeg) is None:
            raise unittest.SkipTest("ffmpeg not available")

        filter_with_text = (
            "drawbox=x=18:y=18:w=190:h=70:color=black@0.95:t=fill,"
            "drawtext=text='LOGO':x=40:y=65:fontsize=40:fontcolor=white"
        )

        base_cmd = [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:sample_rate=44100",
            "-t",
            "3",
            "-vf",
            filter_with_text,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(output_path),
        ]
        proc = subprocess.run(base_cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            return

        fallback_cmd = [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:sample_rate=44100",
            "-t",
            "3",
            "-vf",
            "drawbox=x=18:y=18:w=190:h=70:color=black@0.95:t=fill",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(output_path),
        ]
        fallback_proc = subprocess.run(fallback_cmd, capture_output=True, text=True)
        if fallback_proc.returncode != 0:
            raise AssertionError(f"Failed generating synthetic video: {fallback_proc.stderr}")

    def test_detects_static_overlay_and_sanitizes(self) -> None:
        input_video = self.temp_dir / "input_overlay.mp4"
        output_dir = self.temp_dir / "sanitized"
        output_dir.mkdir(parents=True, exist_ok=True)

        self._create_synthetic_video(input_video)

        cfg = SanitizerConfig(sample_fps=2, max_frames=12, max_mask_area=0.35)
        report = sanitize_video(str(input_video), output_dir, cfg=cfg)

        self.assertNotEqual(report.get("status"), "error")
        detections = report.get("detections") or []
        static_boxes = [d for d in detections if d.get("type") == "static_overlay"]
        self.assertTrue(static_boxes, "Expected at least one static_overlay detection")

        first_bbox = static_boxes[0].get("bbox") or [0, 0, 0, 0]
        self.assertLess(first_bbox[0], 240)
        self.assertLess(first_bbox[1], 180)
        self.assertGreater(first_bbox[2], 30)
        self.assertGreater(first_bbox[3], 20)


if __name__ == "__main__":
    unittest.main()
