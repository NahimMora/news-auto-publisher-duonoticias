import random
import time
from typing import Dict, Iterable, Optional

import httpx

DEFAULT_HEADERS = {
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

RETRY_STATUSES = {429, 500, 502, 503, 504}
BLOCK_STATUSES = {403, 429}


class BlockedError(RuntimeError):
    pass


class HttpClient:
    def __init__(
        self,
        *,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
        retries: int = 3,
        backoff_base: float = 1.0,
        backoff_max: float = 20.0,
        retry_statuses: Optional[Iterable[int]] = None,
        block_statuses: Optional[Iterable[int]] = None,
    ) -> None:
        merged = dict(DEFAULT_HEADERS)
        if headers:
            merged.update({k: v for k, v in headers.items() if v})
        self._headers = merged
        self._timeout = timeout
        self._retries = max(1, int(retries))
        self._backoff_base = max(0.2, float(backoff_base))
        self._backoff_max = max(self._backoff_base, float(backoff_max))
        self._retry_statuses = set(RETRY_STATUSES if retry_statuses is None else retry_statuses)
        self._block_statuses = set(BLOCK_STATUSES if block_statuses is None else block_statuses)
        self._client = httpx.Client(timeout=self._timeout, headers=self._headers, follow_redirects=True)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        headers = kwargs.pop("headers", None)
        merged_headers = dict(self._headers)
        if headers:
            merged_headers.update({k: v for k, v in headers.items() if v})
        last_exc: Optional[Exception] = None
        for attempt in range(self._retries):
            try:
                resp = self._client.request(method, url, headers=merged_headers, **kwargs)
                if resp.status_code in self._block_statuses:
                    raise BlockedError(f"Blocked with status {resp.status_code}")
                if resp.status_code in self._retry_statuses and attempt < self._retries - 1:
                    self._sleep_backoff(attempt)
                    continue
                return resp
            except BlockedError:
                raise
            except httpx.RequestError as exc:
                last_exc = exc
                if attempt < self._retries - 1:
                    self._sleep_backoff(attempt)
                    continue
                break
        if last_exc:
            raise last_exc
        raise RuntimeError("HTTP request failed")

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def _sleep_backoff(self, attempt: int) -> None:
        base = self._backoff_base
        delay = min(self._backoff_max, base * (2 ** attempt))
        jitter = random.uniform(0, delay * 0.1)
        time.sleep(delay + jitter)

    def stream(self, method: str, url: str, **kwargs):
        headers = kwargs.pop("headers", None)
        merged_headers = dict(self._headers)
        if headers:
            merged_headers.update({k: v for k, v in headers.items() if v})
        return self._client.stream(method, url, headers=merged_headers, **kwargs)


def download_to_file(
    url: str,
    output_path: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 60.0,
    retries: int = 3,
    backoff_base: float = 1.0,
    backoff_max: float = 20.0,
    chunk_size: int = 1024 * 1024,
) -> str:
    client = HttpClient(headers=headers, timeout=timeout, retries=1, backoff_base=backoff_base, backoff_max=backoff_max)
    last_exc: Optional[Exception] = None
    try:
        for attempt in range(max(1, retries)):
            try:
                with client.stream("GET", url, follow_redirects=True) as resp:
                    resp.raise_for_status()
                    with open(output_path, "wb") as handle:
                        for chunk in resp.iter_bytes(chunk_size=chunk_size):
                            if chunk:
                                handle.write(chunk)
                return output_path
            except Exception as exc:
                last_exc = exc
                if attempt < max(1, retries) - 1:
                    time.sleep(min(backoff_max, backoff_base * (2 ** attempt)))
                    continue
                break
    finally:
        client.close()
    raise last_exc or RuntimeError("Download failed")
