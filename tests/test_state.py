import json

import pytest

from duonoticias_autopublicador.models import DiscoveredItem
from duonoticias_autopublicador.state import StateStore


def items(count=4):
    return [DiscoveredItem(f"source:https://e/{i}", "news", {"titulo": str(i), "url": f"https://e/{i}"}) for i in range(count)]


@pytest.mark.parametrize(
    "mode,last_n,expected",
    [("mark_seen", 10, {"seen": 4}), ("process_all", 10, {"pending": 4}), ("last_n", 2, {"seen": 2, "pending": 2})],
)
def test_first_run_modes(tmp_path, mode, last_n, expected):
    store = StateStore(tmp_path / "state.db")
    store.ingest(items(), initial_mode=mode, last_n=last_n)
    for status, count in expected.items():
        assert store.counts()[status] == count


def test_after_first_run_new_items_are_pending(tmp_path):
    store = StateStore(tmp_path / "state.db")
    store.ingest(items(1), initial_mode="mark_seen")
    store.ingest(items(2), initial_mode="mark_seen")
    assert store.counts()["seen"] == 1
    assert store.counts()["pending"] == 1


def test_sent_item_changed_is_not_reopened_or_overwritten(tmp_path):
    store = StateStore(tmp_path / "state.db")
    original = items(1)[0]
    store.ingest([original], initial_mode="process_all")
    store.mark_processed(original.key, original.raw)
    store.mark_sent(original.key)
    before = store.get(original.key)
    changed = DiscoveredItem(original.key, "news", {**original.raw, "titulo": "cambio"})
    result = store.ingest([changed])
    after = store.get(original.key)
    assert result["changed_sent"] == 1
    assert after["status"] == "sent"
    assert after["content_hash"] == before["content_hash"]
    assert json.loads(after["raw_json"])["titulo"] == "0"


def test_verify_counts_does_not_create_missing_database(tmp_path):
    path = tmp_path / "missing" / "state.db"
    assert StateStore.read_counts(path) == {"seen": 0, "pending": 0, "processed": 0, "sent": 0, "failed": 0}
    assert not path.exists()
