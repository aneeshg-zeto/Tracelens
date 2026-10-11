"""End-to-end: the real Python SDK sends traces through the real ingestion API into Postgres."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from .conftest import Actor

SDK_PATH = Path(__file__).resolve().parents[3] / "packages" / "python-sdk"
if str(SDK_PATH) not in sys.path:
    sys.path.insert(0, str(SDK_PATH))

tracelens = pytest.importorskip("tracelens")
from tracelens.transport import HttpTransport  # noqa: E402


@pytest.fixture
def sdk(client: Any, api_key: str) -> Any:
    transport = HttpTransport("http://testserver", api_key, client=client, max_retries=0)
    tl = tracelens.TraceLens(transport=transport, set_global=False, register_atexit=False, flush_interval=60)
    yield tl
    tl.shutdown(timeout=5)


def test_sdk_trace_round_trip(sdk: Any, client: Any, owner: Actor, project: dict[str, Any]) -> None:
    with sdk.trace("support-agent", user_id="u-1", tags=["e2e"]) as trace:
        trace.set_input({"question": "refund?"})
        with sdk.span("plan", "agent"):
            with sdk.span("lookup_order", "tool") as tool:
                tool.record_error(TimeoutError("orders-service timed out"))
            with sdk.span("answer", "llm", provider="openai", model="gpt-4o-mini") as llm:
                llm.set_usage(1000, 200)
                llm.set_output({"role": "assistant", "content": "Yes"})
        trace.set_output({"answer": "Yes"})
    assert sdk.flush(timeout=5)
    assert sdk.stats["failed_batches"] == 0

    r = client.get(f"/api/v1/projects/{project['id']}/traces/{trace.trace_id}", headers=owner.headers)
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["trace"]["name"] == "support-agent"
    assert detail["trace"]["source"] == "sdk"
    assert detail["trace"]["span_count"] == 3
    assert detail["trace"]["error_span_count"] == 1
    spans = {s["name"]: s for s in detail["spans"]}
    assert spans["lookup_order"]["parent_span_id"] == spans["plan"]["span_id"]
    assert spans["answer"]["model"] == "gpt-4o-mini"
    assert float(spans["answer"]["cost_usd"]) > 0

    listed = client.get(f"/api/v1/projects/{project['id']}/traces", params={"tag": "e2e"}, headers=owner.headers)
    assert listed.status_code == 200
    assert [t["trace_id"] for t in listed.json()["items"]] == [trace.trace_id]


def test_sdk_whoami_and_rejected_key(sdk: Any, client: Any, project: dict[str, Any]) -> None:
    assert sdk.whoami()["project_id"] == project["id"]
    bad = tracelens.TraceLens(
        transport=HttpTransport("http://testserver", "tl_live_" + "x" * 43, client=client, max_retries=0),
        set_global=False,
        register_atexit=False,
    )
    with bad.trace("never-stored"):
        pass
    bad.flush(timeout=5)
    assert bad.stats["failed_batches"] == 1
    bad.shutdown()
