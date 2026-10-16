from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

import httpx

from publishers.duo_web import (
    DUO_WEB_PLATFORM,
    AdminArticlesDelivery,
    DuoWebPublisher,
    IngestContractDelivery,
    build_admin_payload,
    build_duo_web_publisher,
    build_ingest_payload,
)
from storage.models import FormattedPackage
from storage.settings import get_settings

ROW = {
    "content_key": "abcdef1234567890",
    "source": "holasalta",
    "source_type": "news",
    "canonical_url": "https://www.eltribuno.com/salta/nota/corte-agua",
    "title": "Corte de agua en Salta: qué barrios",
    "summary": "Aguas del Norte anuncio cortes programados.",
    "body_text": "El martes habra cortes en zona norte.",
    "tags_json": json.dumps(["holasalta", "salta"]),
    "raw_payload_json": json.dumps({"id": 7}),
    "editorial_json": json.dumps({"hook": "Atencion"}),
}
PACKAGE = FormattedPackage(content_key="abcdef1234567890", post_type="image", caption="Caption editorial")


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


class DuoWebPayloadTests(unittest.TestCase):
    def test_admin_payload_matches_cms_schema(self) -> None:
        payload = build_admin_payload(PACKAGE, ROW, default_category="world")
        self.assertEqual(payload["title"], ROW["title"])
        self.assertEqual(payload["slug"], "corte-de-agua-en-salta-que-barrios-abcdef12")
        self.assertEqual(payload["category"], "world")
        self.assertIn("Fuente: https://www.eltribuno.com/salta/nota/corte-agua", payload["content"])
        self.assertFalse(payload["isFeatured"] or payload["isHero"] or payload["isBreaking"])

    def test_admin_slug_is_deterministic(self) -> None:
        self.assertEqual(build_admin_payload(PACKAGE, ROW)["slug"], build_admin_payload(PACKAGE, ROW)["slug"])

    def test_admin_category_mapping(self) -> None:
        row = {**ROW, "tags_json": json.dumps(["paparazzi", "espectaculos"])}
        self.assertEqual(build_admin_payload(PACKAGE, row)["category"], "entertainment")

    def test_ingest_payload_follows_contract_v1(self) -> None:
        payload = build_ingest_payload(PACKAGE, ROW)
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["kind"], "news")
        self.assertEqual(payload["source"]["url"], ROW["canonical_url"])
        self.assertEqual(payload["raw"], {"id": 7})
        self.assertEqual(payload["processed"]["editorial"], {"hook": "Atencion"})
        self.assertEqual(len(payload["idempotencyKey"]), 64)
        video = build_ingest_payload(PACKAGE, {**ROW, "source_type": "x_video"})
        self.assertEqual(video["kind"], "video_link")


class DuoWebDeliveryTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_settings.cache_clear()

    def test_admin_delivery_uses_admin_key_and_reads_id(self) -> None:
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["path"] = request.url.path
            seen["key"] = request.headers.get("x-admin-key")
            return httpx.Response(201, json={"data": {"id": "art-1"}})

        publisher = DuoWebPublisher(AdminArticlesDelivery("http://web", "k", client=_client(handler)), get_settings())
        record = publisher.publish(PACKAGE, row=ROW, scheduled_for="2026-10-15T12:00:00+00:00")
        self.assertEqual((seen["path"], seen["key"]), ("/api/admin/articles", "k"))
        self.assertEqual((record.platform, record.status, record.platform_post_id), (DUO_WEB_PLATFORM, "published", "art-1"))

    def test_conflict_counts_as_already_delivered(self) -> None:
        publisher = DuoWebPublisher(
            AdminArticlesDelivery("http://web", "k", client=_client(lambda r: httpx.Response(409, json={"error": "slug"}))),
            get_settings(),
        )
        self.assertEqual(publisher.publish(PACKAGE, row=ROW, scheduled_for="").status, "published")

    def test_ingest_delivery_sends_matching_idempotency_header(self) -> None:
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["header"] = request.headers["Idempotency-Key"]
            seen["auth"] = request.headers["Authorization"]
            seen["body"] = json.loads(request.content)
            return httpx.Response(200)

        publisher = DuoWebPublisher(IngestContractDelivery("http://web", "t", client=_client(handler)), get_settings())
        record = publisher.publish(PACKAGE, row=ROW, scheduled_for="")
        self.assertEqual(record.status, "published")
        self.assertEqual(seen["header"], seen["body"]["idempotencyKey"])
        self.assertEqual(seen["auth"], "Bearer t")

    def test_failures_are_recorded_with_retryability(self) -> None:
        for code, retryable in ((422, False), (503, True)):
            publisher = DuoWebPublisher(
                AdminArticlesDelivery("http://web", "k", client=_client(lambda r, code=code: httpx.Response(code, text="x"))),
                get_settings(),
            )
            record = publisher.publish(PACKAGE, row=ROW, scheduled_for="")
            self.assertEqual(record.status, "publish_failed")
            self.assertEqual(record.payload["retryable"], retryable)

    def test_factory_modes_and_env_fallbacks(self) -> None:
        cases = [
            ({"DUO_WEB_MODE": "disabled", "DUO_WEB_URL": "http://web", "DUO_WEB_TOKEN": "t"}, None, ""),
            ({"DUO_WEB_MODE": "admin", "DUO_WEB_URL": "", "DUO_WEB_TOKEN": "", "DUO_BASE_URL": "http://cms", "DUO_ADMIN_KEY": "adm"}, "admin", "http://cms"),
            ({"DUO_WEB_MODE": "ingest", "DUO_WEB_URL": "", "DUO_WEB_TOKEN": "", "DUO_API_URL": "http://ing/", "DUO_API_TOKEN": "tok"}, "ingest", "http://ing"),
            ({"DUO_WEB_MODE": "ingest", "DUO_WEB_URL": "", "DUO_WEB_TOKEN": "", "DUO_API_URL": "", "DUO_API_TOKEN": ""}, None, ""),
        ]
        for env, mode, url in cases:
            with self.subTest(env=env), patch.dict(os.environ, env, clear=False):
                get_settings.cache_clear()
                publisher = build_duo_web_publisher(get_settings())
                self.assertEqual(publisher.mode if publisher else None, mode)
                if publisher:
                    self.assertEqual(publisher.delivery.base_url, url)

    def test_token_is_not_in_settings_repr(self) -> None:
        with patch.dict(os.environ, {"DUO_WEB_MODE": "ingest", "DUO_WEB_TOKEN": "SUPER-SECRETO", "HS_API_PASSWORD": "OTRO-SECRETO"}, clear=False):
            get_settings.cache_clear()
            text = repr(get_settings())
        self.assertNotIn("SUPER-SECRETO", text)
        self.assertNotIn("OTRO-SECRETO", text)


if __name__ == "__main__":
    unittest.main()
