import httpx
import pytest

from duonoticias_autopublicador.hs_client import HolaSaltaClient


def test_relogin_once_after_401():
    calls = {"login": 0, "get": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            calls["login"] += 1
            return httpx.Response(200, json={"token": f"token-{calls['login']}"})
        calls["get"] += 1
        if calls["get"] == 1:
            return httpx.Response(401)
        assert request.headers["Authorization"] == "Bearer token-2"
        return httpx.Response(200, json=[])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    hs = HolaSaltaClient("http://fake", "admin", "secret", client=client)
    assert hs.get_news() == []
    assert calls == {"login": 2, "get": 2}


def test_backend_down_uses_exponential_backoff_and_stops():
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    hs = HolaSaltaClient(
        "http://fake", "admin", "secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=3, retry_base_seconds=2, sleep=sleeps.append, random_fn=lambda: 0.5,
    )
    with pytest.raises(httpx.ConnectError):
        hs.get_news()
    assert sleeps == [2, 4]


def test_ignores_uploaded_video_jobs_without_source_url():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"token": "x"})
        return httpx.Response(200, json={"items": [
            {"job_id": "file", "source_url": None},
            {"job_id": "link", "source_url": "https://x.com/a/status/1"},
        ], "count": 2})

    hs = HolaSaltaClient("http://fake", "admin", "secret", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert [job["job_id"] for job in hs.get_video_jobs()] == ["link"]

