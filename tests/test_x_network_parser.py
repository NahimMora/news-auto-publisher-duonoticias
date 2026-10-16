from __future__ import annotations

import unittest

from extractors.x.network_parser import extract_video_tweets_from_payload


class XNetworkParserTests(unittest.TestCase):
    def test_extracts_tweet_from_graphql_payload(self) -> None:
        payload = {
            "data": {
                "search_by_raw_query": {
                    "search_timeline": {
                        "timeline": {
                            "instructions": [
                                {
                                    "entries": [
                                        {
                                            "content": {
                                                "itemContent": {
                                                    "tweet_results": {
                                                        "result": {
                                                            "__typename": "Tweet",
                                                            "rest_id": "123",
                                                            "legacy": {
                                                                "full_text": "Video viral de prueba",
                                                                "created_at": "Wed Feb 05 12:00:00 +0000 2025",
                                                                "favorite_count": 100,
                                                                "reply_count": 12,
                                                                "retweet_count": 8,
                                                                "extended_entities": {
                                                                    "media": [
                                                                        {
                                                                            "type": "video",
                                                                            "media_key": "media123",
                                                                            "media_url_https": "https://img.example/thumb.jpg",
                                                                            "video_info": {
                                                                                "duration_millis": 24000,
                                                                                "variants": [
                                                                                    {"content_type": "video/mp4", "bitrate": 256000, "url": "https://cdn.example/low.mp4"},
                                                                                    {"content_type": "video/mp4", "bitrate": 1024000, "url": "https://cdn.example/high.mp4"},
                                                                                ],
                                                                            },
                                                                        }
                                                                    ]
                                                                },
                                                            },
                                                            "views": {"count": "9876"},
                                                            "core": {
                                                                "user_results": {
                                                                    "result": {
                                                                        "legacy": {
                                                                            "name": "Cuenta Test",
                                                                            "screen_name": "cuentatest",
                                                                        }
                                                                    }
                                                                }
                                                            },
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                }
            }
        }

        rows = extract_video_tweets_from_payload(payload)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["tweet_id"], "123")
        self.assertEqual(row["author"], "Cuenta Test")
        self.assertEqual(row["handle"], "cuentatest")
        self.assertEqual(row["visible_metrics"]["views"], 9876.0)
        self.assertEqual(row["media"][0]["url"], "https://cdn.example/high.mp4")
        self.assertEqual(row["duration_seconds"], 24.0)

    def test_uses_core_user_identity_when_legacy_user_is_missing(self) -> None:
        payload = {
            "data": {
                "tweet_result": {
                    "result": {
                        "__typename": "Tweet",
                        "rest_id": "456",
                        "legacy": {
                            "full_text": "Video desde home timeline",
                            "created_at": "Wed Feb 05 13:00:00 +0000 2025",
                            "extended_entities": {
                                "media": [
                                    {
                                        "type": "video",
                                        "media_key": "media456",
                                        "media_url_https": "https://img.example/thumb2.jpg",
                                        "video_info": {
                                            "duration_millis": 12000,
                                            "variants": [
                                                {"content_type": "video/mp4", "bitrate": 512000, "url": "https://cdn.example/home.mp4"}
                                            ],
                                        },
                                    }
                                ]
                            },
                        },
                        "core": {
                            "user_results": {
                                "result": {
                                    "core": {
                                        "name": "Juan Domingo Underwood",
                                        "screen_name": "Ojo_Kritico",
                                    }
                                }
                            }
                        },
                    }
                }
            }
        }

        rows = extract_video_tweets_from_payload(payload)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["author"], "Juan Domingo Underwood")
        self.assertEqual(row["handle"], "Ojo_Kritico")


if __name__ == "__main__":
    unittest.main()
