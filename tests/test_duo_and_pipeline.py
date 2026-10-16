import httpx

from duonoticias_autopublicador.config import Settings
from duonoticias_autopublicador.duo_client import DuoClient
from duonoticias_autopublicador.main import AutoPublisher
from duonoticias_autopublicador.models import DiscoveredItem
from duonoticias_autopublicador.state import StateStore


def prepared_row(tmp_path):
    store = StateStore(tmp_path / "state.db")
    item = DiscoveredItem("source:https://e/1", "news", {"titulo": "T", "url": "https://e/1"})
    store.ingest([item], initial_mode="process_all")
    store.mark_processed(item.key, item.raw)
    return store, item, store.get(item.key)


def test_200_201_and_409_are_success(tmp_path):
    for code in (200, 201, 409):
        client = httpx.Client(transport=httpx.MockTransport(lambda request, code=code: httpx.Response(code)))
        store, item, row = prepared_row(tmp_path / str(code))
        result = DuoClient("http://fake", "token", client=client).send(row)
        assert result.success and not result.retryable


def test_4xx_permanent_and_5xx_or_network_retryable(tmp_path):
    store, item, row = prepared_row(tmp_path)
    r400 = DuoClient("http://fake", "t", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(422, text="bad")))).send(row)
    r500 = DuoClient("http://fake", "t", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))).send(row)
    def offline(request):
        raise httpx.ConnectError("offline", request=request)
    rnet = DuoClient("http://fake", "t", client=httpx.Client(transport=httpx.MockTransport(offline))).send(row)
    assert not r400.success and not r400.retryable
    assert r500.retryable and rnet.retryable


class FakeHS:
    def get_news(self): return []
    def get_video_jobs(self): return []


def settings(tmp_path):
    return Settings(
        hs_api_password="secret", duo_api_url="http://fake", duo_api_token="token",
        state_db_path=tmp_path / "state.db", heartbeat_path=tmp_path / "heartbeat.json",
        initial_sync="process_all", retry_base_seconds=1,
    )


def test_recovery_after_restart_sends_already_processed(tmp_path):
    cfg = settings(tmp_path)
    store, item, row = prepared_row(tmp_path)
    sent = []
    def handler(request):
        sent.append(request.headers["Idempotency-Key"])
        return httpx.Response(201)
    duo = DuoClient("http://fake", "token", client=httpx.Client(transport=httpx.MockTransport(handler)))
    AutoPublisher(cfg, store, FakeHS(), duo).run_once()
    assert len(sent) == 1
    assert store.get(item.key)["status"] == "sent"


def test_idempotency_header_and_body_match(tmp_path):
    store, item, row = prepared_row(tmp_path)
    captured = {}
    def handler(request):
        import json
        captured["header"] = request.headers["Idempotency-Key"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(409)
    result = DuoClient("http://fake", "token", client=httpx.Client(transport=httpx.MockTransport(handler))).send(row)
    assert result.success
    assert captured["header"] == captured["body"]["idempotencyKey"]


def test_publisher_marks_4xx_failed_and_keeps_5xx_for_retry(tmp_path):
    for code, expected in ((422, "failed"), (503, "processed")):
        case = tmp_path / str(code)
        cfg = settings(case)
        store, item, row = prepared_row(case)
        duo = DuoClient(
            "http://fake", "token",
            client=httpx.Client(transport=httpx.MockTransport(lambda request, code=code: httpx.Response(code))),
        )
        AutoPublisher(cfg, store, FakeHS(), duo).run_once()
        saved = store.get(item.key)
        assert saved["status"] == expected
        assert saved["attempts"] == 1


def test_news_without_titulo_sends_empty_title_not_none():
    import json
    from duonoticias_autopublicador.duo_client import build_payload

    row = {"raw_json": json.dumps({"url": "https://e/1"}), "processed_json": "{}", "kind": "news", "key": "k"}
    assert build_payload(row)["title"] == ""
