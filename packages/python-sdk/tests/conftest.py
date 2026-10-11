from __future__ import annotations

import threading
from typing import Any

import pytest

import tracelens
from tracelens import client as client_module


class MemoryTransport:
    """Captures batches and answers API requests from a routing table."""

    def __init__(self) -> None:
        self.batches: list[dict[str, Any]] = []
        self.requests: list[tuple[str, str, Any, Any]] = []
        self.routes: dict[tuple[str, str], Any] = {}
        self.fail = False
        self._lock = threading.Lock()

    def send_batch(self, payload: dict[str, Any]) -> bool:
        with self._lock:
            self.batches.append(payload)
        return not self.fail

    def request(self, method: str, path: str, *, json: Any = None, params: Any = None) -> Any:
        self.requests.append((method, path, json, params))
        handler = self.routes[(method, path)]
        return handler(json, params) if callable(handler) else handler

    def close(self) -> None:
        pass

    @property
    def traces(self) -> list[dict[str, Any]]:
        return [t for b in self.batches for t in b.get("traces", [])]

    @property
    def spans(self) -> list[dict[str, Any]]:
        return [s for b in self.batches for s in b.get("spans", [])]

    def span(self, name: str) -> dict[str, Any]:
        matches = [s for s in self.spans if s["name"] == name]
        assert matches, f"no span named {name!r}; have {[s['name'] for s in self.spans]}"
        return matches[0]


@pytest.fixture
def transport() -> MemoryTransport:
    return MemoryTransport()


@pytest.fixture
def tl(transport: MemoryTransport, monkeypatch: pytest.MonkeyPatch):
    for var in ("TRACELENS_API_KEY", "TRACELENS_BASE_URL", "TRACELENS_ENABLED", "TRACELENS_SAMPLE_RATE"):
        monkeypatch.delenv(var, raising=False)
    client = tracelens.TraceLens(transport=transport, flush_interval=0.05, register_atexit=False)
    yield client
    client.shutdown(timeout=2)
    client_module._global_client = None
