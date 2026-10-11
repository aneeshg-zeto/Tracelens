from __future__ import annotations

import asyncio
import time

import httpx
import pytest

import tracelens
from tracelens.exporter import BatchExporter
from tracelens.transport import HttpTransport, TraceLensError


def test_trace_with_nested_spans(tl, transport):
    with tl.trace("answer", user_id="u-1", session_id="s-1", tags=["prod"]) as t:
        t.set_input({"question": "where is my order?"})
        with tl.span("plan", "agent") as plan, tl.span("lookup", "tool") as tool:
            tool.set_output({"status": "shipped"})
        t.set_output("It shipped.")
    assert tl.flush()

    [trace] = transport.traces
    assert trace["name"] == "answer"
    assert trace["user_id"] == "u-1"
    assert trace["session_id"] == "s-1"
    assert trace["status"] == "ok"
    assert trace["output"] == "It shipped."
    assert trace["end_time"] is not None

    plan_rec, tool_rec = transport.span("plan"), transport.span("lookup")
    assert plan_rec["trace_id"] == trace["trace_id"] == tool_rec["trace_id"]
    assert plan_rec["parent_span_id"] is None
    assert tool_rec["parent_span_id"] == plan.span_id
    assert tool_rec["kind"] == "tool"
    assert tool_rec["output"] == {"status": "shipped"}
    assert tracelens.current_span() is None and tracelens.current_trace() is None


def test_exception_marks_span_and_trace_as_error(tl, transport):
    with pytest.raises(TimeoutError), tl.trace("run"), tl.span("call_api", "tool"):
        raise TimeoutError("upstream timed out")
    tl.flush()
    span = transport.span("call_api")
    assert span["status"] == "error"
    assert span["error"]["type"] == "TimeoutError"
    assert "upstream timed out" in span["error"]["message"]
    assert "Traceback" in span["error"]["stacktrace"]
    assert transport.traces[0]["status"] == "error"


def test_span_without_trace_starts_implicit_trace(tl, transport):
    with tl.span("standalone", "chain") as s:
        s.set_input("in")
        s.set_output("out")
    tl.flush()
    [trace] = transport.traces
    assert trace["name"] == "standalone"
    assert trace["trace_id"] == s.trace_id
    assert trace["input"] == "in" and trace["output"] == "out"


def test_observe_decorator_sync_async_and_generators(tl, transport):
    @tracelens.observe(kind="tool")
    def add(a: int, b: int) -> int:
        return a + b

    @tracelens.observe(name="fetch", kind="retrieval")
    async def fetch(query: str) -> list[str]:
        await asyncio.sleep(0)
        return [query.upper()]

    @tracelens.observe
    def stream(n: int):
        yield from range(n)

    @tracelens.observe(kind="agent")
    def agent() -> int:
        total = add(1, 2)
        asyncio.run(fetch("doc"))
        return total + sum(stream(3))

    assert agent() == 6
    tl.flush()
    root = transport.span("test_observe_decorator_sync_async_and_generators.<locals>.agent")
    add_rec = transport.span("test_observe_decorator_sync_async_and_generators.<locals>.add")
    fetch_rec = transport.span("fetch")
    stream_rec = transport.span("test_observe_decorator_sync_async_and_generators.<locals>.stream")
    assert add_rec["input"] == {"a": 1, "b": 2} and add_rec["output"] == 3
    assert add_rec["parent_span_id"] == root["span_id"]
    assert fetch_rec["parent_span_id"] == root["span_id"]
    assert fetch_rec["kind"] == "retrieval" and fetch_rec["output"] == ["DOC"]
    assert stream_rec["output"] == [0, 1, 2]
    assert len(transport.traces) == 1


def test_observe_records_exceptions(tl, transport):
    @tracelens.observe(kind="tool")
    def broken():
        raise ValueError("bad input")

    with pytest.raises(ValueError):
        broken()
    tl.flush()
    assert transport.spans[0]["status"] == "error"
    assert transport.traces[0]["status"] == "error"


def test_async_context_isolation(tl, transport):
    async def worker(name: str) -> None:
        async with tl.trace(name):
            with tl.span(f"{name}-step", "tool"):
                await asyncio.sleep(0.01)

    async def main() -> None:
        await asyncio.gather(worker("a"), worker("b"))

    asyncio.run(main())
    tl.flush()
    traces = {t["name"]: t["trace_id"] for t in transport.traces}
    assert transport.span("a-step")["trace_id"] == traces["a"]
    assert transport.span("b-step")["trace_id"] == traces["b"]


def test_redaction_of_secrets_and_sensitive_keys(tl, transport):
    with tl.trace("t") as t:
        t.set_input(
            {
                "prompt": "use key sk-proj-abcdefghijklmnopqrstuvwx please",
                "api_key": "hunter2",
                "nested": {"Authorization": "Bearer abc"},
            }
        )
    tl.flush()
    data = transport.traces[0]["input"]
    assert "sk-proj" not in data["prompt"] and "[REDACTED]" in data["prompt"]
    assert data["api_key"] == "[REDACTED]"
    assert data["nested"]["Authorization"] == "[REDACTED]"


def test_pii_redaction_and_custom_redactor(transport):
    client = tracelens.TraceLens(
        transport=transport,
        redact_pii=True,
        set_global=False,
        register_atexit=False,
        redact=lambda v: {**v, "extra": "x"} if isinstance(v, dict) else v,
    )
    with client.trace("t") as t:
        t.set_input({"text": "mail ada@example.com or call +1 415 555 0100"})
    client.flush()
    client.shutdown()
    data = transport.traces[0]["input"]
    assert "ada@example.com" not in data["text"]
    assert "555" not in data["text"]
    assert data["extra"] == "x"


def test_capture_payloads_false_drops_inputs_and_outputs_but_keeps_attributes(transport):
    client = tracelens.TraceLens(
        transport=transport, capture_payloads=False, set_global=False, register_atexit=False
    )
    with client.trace("t", metadata={"tenant": "acme"}) as t:
        t.set_input("secret question")
        with client.span("s", "tool", parent=None) as s:
            s.set_attribute("k", "v")
            s.set_output("secret answer")
    client.flush()
    client.shutdown()
    assert transport.traces[0]["input"] is None
    assert transport.traces[0]["metadata"] == {"tenant": "acme"}
    assert transport.spans[0]["output"] is None
    assert transport.spans[0]["attributes"] == {"k": "v"}


def test_payload_bounds(tl, transport):
    with tl.trace("t") as t:
        t.set_input({"big": "x" * 40_000, "many": list(range(500)), "obj": object()})
    tl.flush()
    data = transport.traces[0]["input"]
    assert len(data["big"]) < 17_000 and "truncated" in data["big"]
    assert len(data["many"]) == 201
    assert data["obj"].startswith("<object object")


def test_sampling_zero_records_nothing(transport):
    client = tracelens.TraceLens(
        transport=transport, sample_rate=0.0, set_global=False, register_atexit=False
    )
    with client.trace("t"), client.span("s"):
        pass
    client.flush()
    client.shutdown()
    assert transport.batches == []


def test_disabled_without_api_key(monkeypatch):
    monkeypatch.delenv("TRACELENS_API_KEY", raising=False)
    client = tracelens.TraceLens(set_global=False, register_atexit=False)
    assert client.enabled is False
    with client.trace("t"), client.span("s"):
        pass
    assert client.flush() is True


def test_exporter_bounded_queue_drops_when_full():
    class Slow:
        def __init__(self) -> None:
            self.count = 0

        def send_batch(self, payload):
            self.count += len(payload.get("spans", []))
            return True

    transport = Slow()
    exporter = BatchExporter(transport, max_queue_size=5, max_batch_size=100, flush_interval=60)  # type: ignore[arg-type]
    accepted = [exporter.put("span", {"i": i}) for i in range(8)]
    assert accepted.count(True) == 5
    assert exporter.dropped == 3
    exporter.flush(2)
    assert transport.count == 5
    exporter.shutdown(1)


def test_exporter_batches_by_size(transport):
    client = tracelens.TraceLens(
        transport=transport, max_batch_size=10, flush_interval=60, set_global=False, register_atexit=False
    )
    with client.trace("t"):
        for i in range(25):
            client.span(f"s{i}").end()
    client.flush()
    client.shutdown()
    sizes = [len(b.get("spans", [])) + len(b.get("traces", [])) for b in transport.batches]
    assert max(sizes) <= 10
    assert sum(sizes) == 26


def test_shutdown_flushes_pending(transport):
    client = tracelens.TraceLens(
        transport=transport, flush_interval=60, set_global=False, register_atexit=False
    )
    with client.trace("t"):
        pass
    client.shutdown()
    assert len(transport.traces) == 1


def _http_transport(handler, **kwargs) -> HttpTransport:
    return HttpTransport(
        "http://tl.test",
        "tl_live_test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        backoff=0.001,
        **kwargs,
    )


def test_http_transport_retries_then_succeeds():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(503, json={"error": {"code": "unavailable", "message": "try later"}})
        return httpx.Response(202, json={"accepted_traces": 1, "accepted_spans": 0, "trace_ids": ["t"]})

    t = _http_transport(handler, max_retries=3)
    assert t.send_batch({"traces": [{"trace_id": "t"}]}) is True
    assert len(calls) == 3
    assert calls[0].headers["Authorization"] == "Bearer tl_live_test"
    assert calls[0].url.path == "/api/v1/ingest/batch"


def test_http_transport_honors_retry_after_and_gives_up():
    calls = []
    started = time.monotonic()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            429,
            headers={"Retry-After": "0"},
            json={"error": {"code": "rate_limited", "message": "slow down"}},
        )

    t = _http_transport(handler, max_retries=2)
    assert t.send_batch({"spans": []}) is False
    assert len(calls) == 3
    assert time.monotonic() - started < 2


def test_http_transport_does_not_retry_client_errors():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(401, json={"error": {"code": "invalid_key", "message": "Invalid API key"}})

    t = _http_transport(handler, max_retries=3)
    assert t.send_batch({"spans": []}) is False
    assert len(calls) == 1
    with pytest.raises(TraceLensError) as info:
        t.request("GET", "/api/v1/ingest/whoami")
    assert info.value.status == 401 and info.value.code == "invalid_key"


def test_http_transport_network_failure_is_contained():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    t = _http_transport(handler, max_retries=1)
    assert t.send_batch({"spans": []}) is False


def test_prompt_fetch_compile_and_link(tl, transport):
    transport.routes[("GET", "/api/v1/ingest/prompts/support")] = {
        "name": "support",
        "version": 3,
        "content": "Hello {{ name }}, about {{topic}}",
        "variables": ["name", "topic"],
    }
    prompt = tl.get_prompt("support")
    assert prompt.version == 3
    assert prompt.compile(name="Ada", topic="billing") == "Hello Ada, about billing"
    with pytest.raises(KeyError):
        prompt.compile(name="Ada")
    assert tl.get_prompt("support") is prompt  # cached
    assert len(transport.requests) == 1
    with tl.span("generate", "llm") as s:
        s.set_prompt(prompt)
    tl.flush()
    attrs = transport.span("generate")["attributes"]
    assert attrs["tracelens.prompt.name"] == "support" and attrs["tracelens.prompt.version"] == 3


def test_run_evaluation_runs_task_and_submits(tl, transport):
    transport.routes[("GET", "/api/v1/ingest/evaluations/datasets/qa")] = {
        "id": "d1",
        "name": "qa",
        "examples": [
            {"id": "e1", "input": {"q": "2+2"}, "expected_output": "4"},
            {"id": "e2", "input": {"q": "boom"}, "expected_output": "x"},
        ],
    }
    transport.routes[("POST", "/api/v1/ingest/evaluations/runs")] = lambda body, _: {
        "id": "r1",
        "status": "completed",
        "received": body,
    }

    def task(inp):
        if inp["q"] == "boom":
            raise RuntimeError("model failed")
        return "4"

    result = tl.run_evaluation(
        "qa", task, ["exact_match", {"type": "contains", "config": {"value": "4"}}], name="baseline"
    )
    body = result["received"]
    assert body["dataset"] == "qa" and body["name"] == "baseline"
    assert body["evaluators"] == [{"type": "exact_match"}, {"type": "contains", "config": {"value": "4"}}]
    r1, r2 = body["results"]
    assert r1["output"] == "4" and r1["error"] is None and r1["latency_ms"] >= 0
    assert r2["error"].startswith("RuntimeError") and r2["output"] is None
    trace_ids = {t["trace_id"] for t in transport.traces}
    assert r1["trace_id"] in trace_ids and r2["trace_id"] in trace_ids
    assert all("evaluation" in t["tags"] for t in transport.traces)


def test_module_level_api_uses_global_client(tl, transport):
    with tracelens.trace("global") as t, tracelens.span("child"):
        pass
    tracelens.flush()
    assert transport.traces[0]["trace_id"] == t.trace_id
    assert tracelens.get_client() is tl
