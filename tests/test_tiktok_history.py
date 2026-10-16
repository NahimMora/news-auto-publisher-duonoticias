from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from utils.tiktok_history import (
    append_tiktok_history,
    build_tiktok_key,
    history_keys,
    load_tiktok_history,
)


class TikTokHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="tiktok_history_test_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_uses_ig_key_when_present(self) -> None:
        video = self.temp_dir / "video.mp4"
        video.write_bytes(b"video-bytes")
        key = build_tiktok_key({"ig_key": "abc123"}, str(video))
        self.assertEqual(key, "abc123")

    def test_hash_key_and_history_dedup(self) -> None:
        history_path = self.temp_dir / "noticias_publicadas_tiktok.json"
        video = self.temp_dir / "video_hash.mp4"
        video.write_bytes(b"video-content-for-hash")

        key = build_tiktok_key({}, str(video))
        created = append_tiktok_history(
            history_path,
            key=key,
            video=str(video),
            caption="caption",
            post_url="https://www.tiktok.com/@test/video/1",
        )

        self.assertEqual(created.get("key"), key)

        rows = load_tiktok_history(history_path)
        keys = history_keys(rows)
        self.assertIn(key, keys)

        # Re-appending the same key should not duplicate rows.
        append_tiktok_history(
            history_path,
            key=key,
            video=str(video),
            caption="caption",
            post_url="https://www.tiktok.com/@test/video/1",
        )
        rows_after = load_tiktok_history(history_path)
        self.assertEqual(len(rows_after), 1)


if __name__ == "__main__":
    unittest.main()
