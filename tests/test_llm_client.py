from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

import httpx

from utils import llm_client
from utils.llm_client import LLMConfig, LLMError, generate_json, generate_text, llm_config_from_env

GEMINI = LLMConfig(
    provider="gemini",
    model="gemini-3.1-flash-lite",
    base_url="https://generativelanguage.googleapis.com/v1beta",
    api_key="KEY-SECRETA",
    thinking_level="minimal",
)


class FakeHttpClient:
    calls: list = []
    response = httpx.Response(200, json={})

    def __init__(self, *, headers=None, **kwargs) -> None:
        self.headers = headers or {}
        self.kwargs = kwargs

    def post(self, url, json=None):
        FakeHttpClient.calls.append({"url": url, "headers": self.headers, "json": json, "kwargs": self.kwargs})
        return FakeHttpClient.response

    def close(self) -> None:
        pass


def _gemini_response(text: str) -> httpx.Response:
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]})


class LLMClientTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeHttpClient.calls = []
        patcher = patch.object(llm_client, "HttpClient", FakeHttpClient)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_gemini_request_shape(self) -> None:
        FakeHttpClient.response = _gemini_response('{"decision": "publish"}')
        result = generate_json("sistema", "usuario", temperature=0.5, max_output_tokens=1234, config=GEMINI)
        self.assertEqual(result, {"decision": "publish"})
        call = FakeHttpClient.calls[0]
        self.assertEqual(
            call["url"], "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent"
        )
        self.assertEqual(call["headers"]["x-goog-api-key"], "KEY-SECRETA")
        self.assertNotIn("KEY-SECRETA", call["url"])
        body = call["json"]
        self.assertEqual(body["systemInstruction"], {"parts": [{"text": "sistema"}]})
        self.assertEqual(body["contents"], [{"role": "user", "parts": [{"text": "usuario"}]}])
        config = body["generationConfig"]
        self.assertEqual((config["temperature"], config["maxOutputTokens"]), (0.5, 1234))
        self.assertEqual(config["responseMimeType"], "application/json")
        self.assertEqual(config["thinkingConfig"], {"thinkingLevel": "minimal"})
        # 429 is retried as a rate limit, not raised as a scraper block.
        self.assertIn(429, call["kwargs"]["retry_statuses"])
        self.assertEqual(call["kwargs"]["block_statuses"], set())

    def test_plain_text_has_no_json_mime(self) -> None:
        FakeHttpClient.response = _gemini_response("texto curado")
        self.assertEqual(generate_text("s", "u", config=GEMINI), "texto curado")
        self.assertNotIn("responseMimeType", FakeHttpClient.calls[0]["json"]["generationConfig"])

    def test_thought_parts_are_ignored(self) -> None:
        data = {"candidates": [{"content": {"parts": [{"text": "pensando", "thought": True}, {"text": "respuesta"}]}}]}
        self.assertEqual(llm_client.extract_gemini_text(data), "respuesta")

    def test_empty_candidate_reports_finish_reason(self) -> None:
        FakeHttpClient.response = httpx.Response(200, json={"candidates": [{"finishReason": "MAX_TOKENS"}]})
        with self.assertRaisesRegex(LLMError, "MAX_TOKENS"):
            generate_text("s", "u", config=GEMINI)

    def test_http_error_message_has_no_key(self) -> None:
        FakeHttpClient.response = httpx.Response(400, text="bad request")
        with self.assertRaises(LLMError) as ctx:
            generate_text("s", "u", config=GEMINI)
        self.assertNotIn("KEY-SECRETA", str(ctx.exception))

    def test_missing_key_fails_before_network(self) -> None:
        with self.assertRaisesRegex(LLMError, "GEMINI_API_KEY"):
            generate_text("s", "u", config=LLMConfig("gemini", "m", "u", ""))
        self.assertEqual(FakeHttpClient.calls, [])

    def test_json_wrapped_in_fences_is_parsed(self) -> None:
        FakeHttpClient.response = _gemini_response('```json\n{"a": 1}\n```')
        self.assertEqual(generate_json("s", "u", config=GEMINI), {"a": 1})

    def test_openai_rollback_keeps_responses_api(self) -> None:
        FakeHttpClient.response = httpx.Response(200, json={"output_text": "hola"})
        cfg = LLMConfig("openai", "gpt-4.1-mini", "https://api.openai.com/v1/responses", "sk")
        self.assertEqual(generate_text("s", "u", config=cfg), "hola")
        self.assertEqual(FakeHttpClient.calls[0]["headers"]["Authorization"], "Bearer sk")


class FallbackTests(unittest.TestCase):
    """Saturacion (503) del modelo principal: una vez con el respaldo lite, mas barato."""

    def setUp(self) -> None:
        self.calls = []
        responses = self.responses = []

        class Scripted(FakeHttpClient):
            def post(inner, url, json=None):
                self.calls.append({"url": url, "json": json})
                return responses.pop(0)

        patcher = patch.object(llm_client, "HttpClient", Scripted)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cfg = LLMConfig("gemini", "gemini-3.1-flash-lite", "https://g/v1beta", "K", "minimal", fallback_model="gemini-3.5-flash-lite")

    def test_503_uses_fallback_model(self) -> None:
        self.responses += [httpx.Response(503, json={"error": {"code": 503, "message": "high demand"}}), _gemini_response('{"ok": 1}')]
        payload, usage = llm_client.generate_json_with_usage("s", "u", config=self.cfg)
        self.assertEqual(payload, {"ok": 1})
        self.assertEqual(usage.model, "gemini-3.5-flash-lite")
        self.assertEqual(usage.fallback_from, "gemini-3.1-flash-lite")
        self.assertIn("gemini-3.5-flash-lite:generateContent", self.calls[1]["url"])

    def test_gemini_2_models_get_no_thinking_level(self) -> None:
        cfg = LLMConfig("gemini", "gemini-2.5-flash", "https://g/v1beta", "K", "minimal")
        self.responses += [_gemini_response('{"ok": 1}')]
        llm_client.generate_json_with_usage("s", "u", config=cfg)
        self.assertNotIn("thinkingConfig", self.calls[0]["json"]["generationConfig"])

    def test_other_errors_do_not_switch_model(self) -> None:
        self.responses += [httpx.Response(400, json={"error": {"message": "bad request"}})]
        with self.assertRaises(LLMError):
            llm_client.generate_json_with_usage("s", "u", config=self.cfg)
        self.assertEqual(len(self.calls), 1)

    def test_fallback_can_be_disabled(self) -> None:
        cfg = LLMConfig("gemini", "gemini-3.1-flash-lite", "https://g/v1beta", "K", "minimal", fallback_model="")
        self.responses += [httpx.Response(503, json={"error": {"code": 503}})]
        with self.assertRaises(LLMError):
            llm_client.generate_json_with_usage("s", "u", config=cfg)


class LLMConfigTests(unittest.TestCase):
    def test_defaults_to_gemini_flash_lite(self) -> None:
        with patch.dict(os.environ, {"LLM_PROVIDER": "", "GEMINI_MODEL": "", "GEMINI_API_KEY": "k"}):
            cfg = llm_config_from_env()
        self.assertEqual((cfg.provider, cfg.model, cfg.thinking_level), ("gemini", "gemini-3.1-flash-lite", "minimal"))
        self.assertTrue(cfg.ready)
        self.assertNotIn("'k'", repr(cfg))

    def test_openai_provider(self) -> None:
        with patch.dict(os.environ, {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk", "OPENAI_MODEL": ""}):
            cfg = llm_config_from_env()
        self.assertEqual((cfg.provider, cfg.model, cfg.api_key_env), ("openai", "gpt-4.1-mini", "OPENAI_API_KEY"))


if __name__ == "__main__":
    unittest.main()
