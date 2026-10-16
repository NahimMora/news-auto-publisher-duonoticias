"""Single text-generation client for the pipeline (Gemini by default, OpenAI as rollback).

Every caller that used to post to the OpenAI Responses API goes through
``generate_text``. Provider and model come from ``.env``:

- ``LLM_PROVIDER=gemini`` (default) uses ``GEMINI_API_KEY`` / ``GEMINI_MODEL``
  (``gemini-3.1-flash-lite``) against ``generateContent``. The key travels in the
  ``x-goog-api-key`` header, never in the URL, so it cannot leak into error logs.
- ``LLM_PROVIDER=openai`` keeps the previous behaviour (``OPENAI_*`` variables).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from utils.http_client import HttpClient

GEMINI_DEFAULT_MODEL = "gemini-3.1-flash-lite"
GEMINI_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
OPENAI_DEFAULT_MODEL = "gpt-4.1-mini"
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1/responses"
# Gemini counts thinking tokens inside maxOutputTokens; callers' budgets
# (300-900 tokens) were sized for non-thinking OpenAI models, so keep it minimal.
GEMINI_DEFAULT_THINKING_LEVEL = "minimal"
# 429 is a rate limit here, not a scraper block: retry it with backoff.
_RETRY_STATUSES = {429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    base_url: str
    api_key: str = field(repr=False)
    thinking_level: str = ""

    @property
    def ready(self) -> bool:
        return bool(self.api_key)

    @property
    def api_key_env(self) -> str:
        return "GEMINI_API_KEY" if self.provider == "gemini" else "OPENAI_API_KEY"


def llm_config_from_env() -> LLMConfig:
    provider = (os.getenv("LLM_PROVIDER") or "gemini").strip().lower()
    if provider == "openai":
        return LLMConfig(
            provider="openai",
            model=(os.getenv("OPENAI_MODEL") or OPENAI_DEFAULT_MODEL).strip(),
            base_url=(os.getenv("OPENAI_BASE_URL") or OPENAI_DEFAULT_BASE_URL).strip(),
            api_key=(os.getenv("OPENAI_API_KEY") or "").strip(),
        )
    return LLMConfig(
        provider="gemini",
        model=(os.getenv("GEMINI_MODEL") or GEMINI_DEFAULT_MODEL).strip(),
        base_url=(os.getenv("GEMINI_BASE_URL") or GEMINI_DEFAULT_BASE_URL).strip().rstrip("/"),
        api_key=(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip(),
        thinking_level=(os.getenv("GEMINI_THINKING_LEVEL") or GEMINI_DEFAULT_THINKING_LEVEL).strip().lower(),
    )


def generate_text(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.7,
    max_output_tokens: int = 900,
    json_output: bool = False,
    timeout: float = 90.0,
    config: Optional[LLMConfig] = None,
) -> str:
    cfg = config or llm_config_from_env()
    if not cfg.ready:
        raise LLMError(f"Missing {cfg.api_key_env}")
    if cfg.provider == "openai":
        return _openai(cfg, system_prompt, user_prompt, temperature, max_output_tokens, timeout)
    return _gemini(cfg, system_prompt, user_prompt, temperature, max_output_tokens, json_output, timeout)


def generate_json(system_prompt: str, user_prompt: str, **kwargs: Any) -> Dict[str, Any]:
    text = generate_text(system_prompt, user_prompt, json_output=True, **kwargs)
    parsed = parse_json_object(text)
    if parsed is None:
        raise LLMError("Respuesta IA invalida: sin objeto JSON")
    return parsed


def parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    cleaned = (text or "").strip()
    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except (ValueError, TypeError):
        pass
    match = re.search(r"\{.*\}", cleaned, re.S)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _post(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    client = HttpClient(
        headers=headers,
        timeout=timeout,
        retries=3,
        backoff_base=2,
        backoff_max=30,
        retry_statuses=_RETRY_STATUSES,
        block_statuses=set(),
    )
    try:
        response = client.post(url, json=payload)
        if response.status_code >= 400:
            # Body only: the URL and headers never carry the key for Gemini, but stay out of messages anyway.
            raise LLMError(f"HTTP {response.status_code}: {response.text[:300]}")
        return response.json()
    finally:
        client.close()


def _gemini(
    cfg: LLMConfig,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_output_tokens: int,
    json_output: bool,
    timeout: float,
) -> str:
    generation_config: Dict[str, Any] = {"temperature": temperature, "maxOutputTokens": max_output_tokens}
    if json_output:
        generation_config["responseMimeType"] = "application/json"
    if cfg.thinking_level:
        generation_config["thinkingConfig"] = {"thinkingLevel": cfg.thinking_level}
    payload: Dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": generation_config,
    }
    if system_prompt:
        payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}
    url = f"{cfg.base_url}/models/{cfg.model}:generateContent"
    headers = {"x-goog-api-key": cfg.api_key, "Content-Type": "application/json"}
    data = _post(url, headers, payload, timeout)
    text = extract_gemini_text(data)
    if not text:
        reason = ""
        candidates = data.get("candidates") or []
        if candidates:
            reason = str(candidates[0].get("finishReason") or "")
        block = (data.get("promptFeedback") or {}).get("blockReason") or ""
        raise LLMError(f"Gemini sin texto (finishReason={reason or '-'} blockReason={block or '-'})")
    return text


def extract_gemini_text(data: Dict[str, Any]) -> str:
    chunks = []
    for candidate in (data.get("candidates") or [])[:1]:
        for part in (candidate.get("content") or {}).get("parts") or []:
            if part.get("text") and not part.get("thought"):
                chunks.append(part["text"])
    return "".join(chunks).strip()


def _openai(
    cfg: LLMConfig,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_output_tokens: int,
    timeout: float,
) -> str:
    payload = {
        "model": cfg.model,
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
            {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
        ],
    }
    headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}
    data = _post(cfg.base_url, headers, payload, timeout)
    direct = str(data.get("output_text") or "").strip()
    if direct:
        return direct
    chunks = []
    for item in data.get("output") or []:
        for block in item.get("content") or []:
            if block.get("type") == "output_text" and block.get("text"):
                chunks.append(block["text"])
    return "\n".join(chunks).strip()
