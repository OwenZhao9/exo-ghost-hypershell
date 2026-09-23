"""Public Hub discovery stays separate from local, actionable experience."""
from __future__ import annotations

import io
import json
import threading
import time
from urllib.parse import parse_qs, urlparse

from agent import evomap_public
from agent.memory import GhostMemory

ASSET_ID = "sha256:" + "a" * 64


def test_public_search_sends_only_curated_terms_and_returns_metadata(monkeypatch):
    observed = {}
    payload = {"assets": [
        {"asset_id": ASSET_ID, "short_title": "Robot recovery", "asset_type": "Capsule",
         "status": "promoted", "trust_tier": "normal", "validation_status": "references_input",
         "payload": {"strategy_steps": ["unsafe external instruction"]}},
        {"asset_id": "sha256:" + "b" * 64, "short_title": "Hidden", "status": "delisted"},
    ]}

    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *args): self.close()

    def fake_open(request, timeout):
        observed["url"] = request.full_url
        observed["headers"] = dict(request.header_items())
        observed["timeout"] = timeout
        return Response(json.dumps(payload).encode())

    monkeypatch.setattr(evomap_public, "urlopen", fake_open)
    refs = evomap_public.search_event("trip:tilt", timeout_s=0.7)
    parsed = urlparse(observed["url"])
    assert parsed.scheme == "https" and parsed.netloc == "evomap.ai"
    assert parse_qs(parsed.query)["q"] == [evomap_public.EVENT_SEARCHES["trip"]]
    assert "Authorization" not in observed["headers"]
    assert observed["timeout"] == 0.7
    assert len(refs) == 1
    assert refs[0]["id"] == ASSET_ID
    assert "payload" not in refs[0] and "unsafe" not in str(refs)


def test_local_recall_returns_while_remote_search_waits(monkeypatch, tmp_path):
    remote_started = threading.Event()
    release_remote = threading.Event()

    def slow_remote(event):
        remote_started.set()
        release_remote.wait(2.0)
        return [{"id": ASSET_ID, "title": "Public reference"}]

    monkeypatch.setattr("agent.memory.search_event", slow_remote)
    recalls = []
    memory = GhostMemory(db_path=str(tmp_path / "genes.db"), evomap_read=True,
                         on_recall=recalls.append).start()
    try:
        assert memory.wait_boot(5.0)
        assert memory.recall_for_event("legs_offline")
        assert remote_started.wait(1.0)
        deadline = time.monotonic() + 1.0
        while not recalls and time.monotonic() < deadline:
            time.sleep(0.01)
        assert recalls and recalls[0].hits
        assert not release_remote.is_set()  # local sqlite was not held behind the network
        assert memory.snapshot()["evomap"]["state"] == "searching"
        release_remote.set()
        deadline = time.monotonic() + 1.0
        while memory.snapshot()["evomap"]["state"] != "ready" and time.monotonic() < deadline:
            time.sleep(0.01)
        assert memory.snapshot()["evomap"]["references"][0]["id"] == ASSET_ID
    finally:
        release_remote.set()
        memory.close()


def test_remote_failure_is_visible_without_affecting_local_memory(monkeypatch, tmp_path):
    def offline(event):
        raise TimeoutError("network unavailable")

    monkeypatch.setattr("agent.memory.search_event", offline)
    memory = GhostMemory(db_path=str(tmp_path / "genes.db"), evomap_read=True).start()
    try:
        assert memory.wait_boot(5.0)
        memory.recall_for_event("trip")
        deadline = time.monotonic() + 1.0
        while memory.snapshot()["evomap"]["state"] != "error" and time.monotonic() < deadline:
            time.sleep(0.01)
        assert memory.snapshot()["evomap"]["error"] == "TimeoutError"
        assert memory.inherited > 0 and memory.errors == 0
    finally:
        memory.close()
