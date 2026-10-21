from __future__ import annotations

import unittest

from extractors.news.common import content_from_raw, extract_article_fields


class NewsCommonTests(unittest.TestCase):
    def test_extract_article_fields_ignores_tracking_iframe_as_video(self) -> None:
        fields = extract_article_fields(
            """
            <html>
              <head>
                <meta property="og:title" content="Titulo">
                <meta property="og:image" content="https://cdn.example.com/foto.jpg">
              </head>
              <body>
                <iframe src="https://www.googletagmanager.com/ns.html?id=GTM-1"></iframe>
                <video src="https://cdn.example.com/video.mp4"></video>
              </body>
            </html>
            """,
            "https://example.com/nota",
            title_hint="Titulo",
        )

        self.assertEqual(fields["video_urls"], ["https://cdn.example.com/video.mp4"])
        self.assertEqual(fields["image_urls"], ["https://cdn.example.com/foto.jpg"])

    def test_extract_article_fields_preserves_image_query_string(self) -> None:
        fields = extract_article_fields(
            """
            <html>
              <head>
                <meta property="og:title" content="Titulo">
                <meta property="og:image" content="https://cdn.example.com/foto.jpg?auth=abc123&amp;width=1200">
              </head>
            </html>
            """,
            "https://example.com/nota",
            title_hint="Titulo",
        )

        self.assertEqual(
            fields["image_urls"],
            ["https://cdn.example.com/foto.jpg?auth=abc123&width=1200"],
        )

    def test_content_from_raw_downgrades_invalid_video_to_image_post(self) -> None:
        content = content_from_raw(
            source="tn",
            source_type="news",
            raw={
                "titulo": "Nota politica relevante",
                "url": "https://tn.com.ar/politica/2026/05/03/nota",
                "image_urls": ["https://cdn.example.com/foto.jpg"],
                "video_urls": ["https://www.googletagmanager.com/ns.html"],
                "fecha_publicacion": "Sun, 03 May 2026 15:00:00 GMT",
            },
            category="nacional",
        )

        self.assertEqual(content.media_type, "image")
        self.assertEqual([asset.kind for asset in content.assets], ["image"])


if __name__ == "__main__":
    unittest.main()


def test_is_valid_image_url_keeps_wordpress_uploads():
    from extractors.news.html_scraper import is_valid_image_url

    assert is_valid_image_url("https://nuevodiariodesalta.com.ar/wp-content/uploads/2026/10/854043206_n.jpg")
    assert not is_valid_image_url("https://example.com/static/logo-duo.png")
    assert not is_valid_image_url("https://example.com/ads/banner_300x250.jpg")
    assert not is_valid_image_url("https://example.com/img/favicon.ico")
