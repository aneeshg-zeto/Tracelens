from __future__ import annotations

import time
from typing import Any

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span, Status

from .conftest import Actor

TRACE_HEX = "0af7651916cd43dd8448eb211c80319c"
ROOT_HEX = "b7ad6b7169203331"
CHILD_HEX = "00f067aa0ba902b7"


def _kv(key: str, value: Any) -> KeyValue:
    if isinstance(value, int):
        return KeyValue(key=key, value=AnyValue(int_value=value))
    return KeyValue(key=key, value=AnyValue(string_value=str(value)))


def _protobuf_body(now_ns: int) -> bytes:
    root = Span(
        trace_id=bytes.fromhex(TRACE_HEX),
        span_id=bytes.fromhex(ROOT_HEX),
        name="invoke_agent support",
        start_time_unix_nano=now_ns - 2_000_000_000,
        end_time_unix_nano=now_ns,
        attributes=[_kv("gen_ai.operation.name", "invoke_agent")],
    )
    child = Span(
        trace_id=bytes.fromhex(TRACE_HEX),
        span_id=bytes.fromhex(CHILD_HEX),
        parent_span_id=bytes.fromhex(ROOT_HEX),
        name="chat gpt-4o",
        start_time_unix_nano=now_ns - 1_500_000_000,
        end_time_unix_nano=now_ns - 500_000_000,
        attributes=[
            _kv("gen_ai.system", "openai"),
            _kv("gen_ai.request.model", "gpt-4o"),
            _kv("gen_ai.usage.input_tokens", 500),
            _kv("gen_ai.usage.output_tokens", 50),
        ],
        status=Status(code=Status.STATUS_CODE_ERROR, message="rate limited"),
    )
    req = ExportTraceServiceRequest(
        resource_spans=[
            ResourceSpans(
                resource={
                    "attributes": [
                        _kv("service.name", "support-bot"),
                        _kv("deployment.environment.name", "staging"),
                    ]
                },
                scope_spans=[ScopeSpans(spans=[root, child])],
            )
        ]
    )
    return req.SerializeToString()


def test_otlp_protobuf(client: Any, owner: Actor, project: dict[str, Any], api_key: str) -> None:
    r = client.post(
        "/api/v1/otlp/v1/traces",
        content=_protobuf_body(time.time_ns()),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/x-protobuf"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/x-protobuf"

    detail = client.get(f"/api/v1/projects/{project['id']}/traces/{TRACE_HEX}", headers=owner.headers).json()
    t = detail["trace"]
    assert t["source"] == "otlp" and t["environment"] == "staging" and t["span_count"] == 2
    assert t["total_tokens"] == 550 and t["models"] == ["gpt-4o"]
    spans = {s["span_id"]: s for s in detail["spans"]}
    assert spans[ROOT_HEX]["kind"] == "agent"
    child = spans[CHILD_HEX]
    assert child["kind"] == "llm" and child["parent_span_id"] == ROOT_HEX
    assert child["status"] == "error" and child["error_message"] == "rate limited"


def test_otlp_json(client: Any, owner: Actor, project: dict[str, Any], api_key: str) -> None:
    now = time.time_ns()
    body = {
        "resourceSpans": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "rag"}}]},
                "scopeSpans": [
                    {
                        "scope": {"name": "manual"},
                        "spans": [
                            {
                                "traceId": TRACE_HEX,
                                "spanId": ROOT_HEX,
                                "name": "retrieve",
                                "startTimeUnixNano": str(now - 1_000_000_000),
                                "endTimeUnixNano": str(now),
                                "attributes": [
                                    {"key": "openinference.span.kind", "value": {"stringValue": "RETRIEVER"}}
                                ],
                                "status": {"code": 1},
                            }
                        ],
                    }
                ],
            }
        ]
    }
    r = client.post("/api/v1/otlp/v1/traces", json=body, headers={"Authorization": f"Bearer {api_key}"})
    assert r.status_code == 200, r.text
    detail = client.get(f"/api/v1/projects/{project['id']}/traces/{TRACE_HEX}", headers=owner.headers).json()
    assert detail["spans"][0]["kind"] == "retrieval"
    assert detail["trace"]["status"] == "ok"


def test_otlp_errors(client: Any, api_key: str) -> None:
    auth = {"Authorization": f"Bearer {api_key}"}
    r = client.post(
        "/api/v1/otlp/v1/traces",
        content=b"\xff\xfe garbage",
        headers={**auth, "Content-Type": "application/x-protobuf"},
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_otlp"
    r = client.post("/api/v1/otlp/v1/traces", content=b"{}", headers={**auth, "Content-Type": "text/plain"})
    assert r.status_code == 400
    r = client.post(
        "/api/v1/otlp/v1/traces",
        content=b"x",
        headers={**auth, "Content-Type": "application/x-protobuf", "Content-Encoding": "gzip"},
    )
    assert r.status_code == 415
    bad_id = {"resourceSpans": [{"scopeSpans": [{"spans": [{"traceId": "xyz", "spanId": ROOT_HEX}]}]}]}
    assert client.post("/api/v1/otlp/v1/traces", json=bad_id, headers=auth).status_code == 400
