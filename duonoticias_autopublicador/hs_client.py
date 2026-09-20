from __future__ import annotations

import random
import time
from typing import Any, Callable

import httpx


class HolaSaltaClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        client: httpx.Client | None = None,
        max_retries: int = 5,
        retry_base_seconds: float = 1.0,
        retry_max_seconds: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        random_fn: Callable[[], float] = random.random,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.client = client or httpx.Client(timeout=30.0)
        self.max_retries = max_retries
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds
        self.sleep = sleep
        self.random_fn = random_fn
        self._token: str | None = None

    def _login(self) -> None:
        response = self.client.post(
            f"{self.base_url}/api/auth/login",
            json={"username": self.username, "password": self.password},
        )
        response.raise_for_status()
        token = response.json().get("token")
        if not token:
            raise ValueError("HolaSalta login no devolvio token")
        self._token = str(token)

    def _request_once(self, path: str) -> httpx.Response:
        if self._token is None:
            self._login()
        response = self.client.get(
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=30.0,
        )
        if response.status_code == 401:
            self._token = None
            self._login()
            response = self.client.get(
                f"{self.base_url}{path}",
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=30.0,
            )
        response.raise_for_status()
        return response

    def _get(self, path: str) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                return self._request_once(path).json()
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code >= 500
                if not retryable or attempt + 1 >= self.max_retries:
                    raise
                delay = min(self.retry_max_seconds, self.retry_base_seconds * (2**attempt))
                self.sleep(delay * (0.5 + self.random_fn()))
        raise RuntimeError("reintentos agotados") from last_error

    def get_news(self) -> list[dict[str, Any]]:
        data = self._get("/api/news/")
        if not isinstance(data, list):
            raise ValueError("HolaSalta /api/news/ no devolvio una lista")
        return [item for item in data if isinstance(item, dict)]

    def get_video_jobs(self) -> list[dict[str, Any]]:
        data = self._get("/api/x-video/jobs?limit=100")
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise ValueError("HolaSalta /api/x-video/jobs devolvio un formato invalido")
        return [item for item in data["items"] if isinstance(item, dict) and item.get("source_url")]

    def close(self) -> None:
        self.client.close()

