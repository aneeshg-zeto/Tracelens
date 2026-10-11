"""OTLP/HTTP trace ingestion mapping.

Supported:
* ExportTraceServiceRequest encoded as application/x-protobuf (decoded with the
  official opentelemetry-proto classes) or application/json (OTLP JSON: hex
  trace/span ids, lowerCamelCase keys, int64 as string or number).
* IDs, parent ids, names, timestamps, status, attributes, resource attributes,
  and "exception" span events.
* GenAI semantic conventions (gen_ai.*), a subset of OpenInference attributes
  (openinference.span.kind, llm.*, input.value/output.value), and HTTP
  attributes for span classification.

Not supported (ignored): span links, non-exception events, dropped counts,
trace state, instrumentation scope versions, and gzip-compressed bodies (send
uncompressed or put a collector in front).
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any

from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue
from pydantic import ValidationError

from app.schemas.ingest import ErrorIn, IngestBatch, SpanIn, TraceIn, UsageIn


class OTLPDecodeError(ValueError):
    pass


OPENINFERENCE_KINDS = {
    "LLM": "llm",
    "EMBEDDING": "llm",
    "TOOL": "tool",
    "RETRIEVER": "retrieval",
    "RERANKER": "retrieval",
    "CHAIN": "chain",
    "AGENT": "agent",
}
VALID_KINDS = {"llm", "tool", "retrieval", "chain", "agent", "http", "custom", "other"}
CONSUMED_ATTRIBUTES = {
    "tracelens.span.kind",
    "gen_ai.prompt",
    "gen_ai.completion",
    "input.value",
    "output.value",
}


# --- Decoding -----------------------------------------------------------------


def _any_value_pb(v: AnyValue) -> Any:
    which = v.WhichOneof("value")
    if which is None:
        return None
    if which == "array_value":
        return [_any_value_pb(x) for x in v.array_value.values]
    if which == "kvlist_value":
        return {kv.key: _any_value_pb(kv.value) for kv in v.kvlist_value.values}
    if which == "bytes_value":
        return base64.b64encode(v.bytes_value).decode()
    return getattr(v, which)


def _attrs_pb(kvs: Any) -> dict[str, Any]:
    return {kv.key: _any_value_pb(kv.value) for kv in kvs}


def _from_protobuf(body: bytes) -> list[dict[str, Any]]:
    req = ExportTraceServiceRequest()
    try:
        req.ParseFromString(body)
    except DecodeError as exc:
        raise OTLPDecodeError("body is not a valid ExportTraceServiceRequest protobuf") from exc
    out: list[dict[str, Any]] = []
    for rs in req.resource_spans:
        resource = _attrs_pb(rs.resource.attributes)
        for ss in rs.scope_spans:
            for sp in ss.spans:
                out.append(
                    {
                        "trace_id": sp.trace_id.hex(),
                        "span_id": sp.span_id.hex(),
                        "parent_span_id": sp.parent_span_id.hex() or None,
                        "name": sp.name,
                        "kind": int(sp.kind),
                        "start_ns": int(sp.start_time_unix_nano),
                        "end_ns": int(sp.end_time_unix_nano),
                        "attributes": _attrs_pb(sp.attributes),
                        "status_code": int(sp.status.code),
                        "status_message": sp.status.message,
                        "events": [
                            {"name": e.name, "attributes": _attrs_pb(e.attributes)} for e in sp.events
                        ],
                        "resource": resource,
                        "scope": ss.scope.name,
                    }
                )
    return out


def _any_value_json(v: dict[str, Any]) -> Any:
    if not isinstance(v, dict):
        return v
    if "stringValue" in v:
        return v["stringValue"]
    if "boolValue" in v:
        return bool(v["boolValue"])
    if "intValue" in v:
        return int(v["intValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "arrayValue" in v:
        return [_any_value_json(x) for x in v["arrayValue"].get("values", [])]
    if "kvlistValue" in v:
        return {kv["key"]: _any_value_json(kv.get("value", {})) for kv in v["kvlistValue"].get("values", [])}
    if "bytesValue" in v:
        return v["bytesValue"]
    return None


def _attrs_json(kvs: Any) -> dict[str, Any]:
    if not isinstance(kvs, list):
        return {}
    return {
        kv["key"]: _any_value_json(kv.get("value", {})) for kv in kvs if isinstance(kv, dict) and "key" in kv
    }


def _hex_id(value: Any, length: int) -> str | None:
    if not value:
        return None
    s = str(value).lower()
    if len(s) != length or any(c not in "0123456789abcdef" for c in s):
        raise OTLPDecodeError(f"invalid OTLP id {value!r}: expected {length} hex characters")
    if set(s) == {"0"}:
        return None
    return s


def _from_json(body: bytes) -> list[dict[str, Any]]:
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise OTLPDecodeError("body is not valid JSON") from exc
    if not isinstance(data, dict):
        raise OTLPDecodeError("expected a JSON object")
    out: list[dict[str, Any]] = []
    try:
        for rs in data.get("resourceSpans", []):
            resource = _attrs_json(rs.get("resource", {}).get("attributes", []))
            for ss in rs.get("scopeSpans", []):
                for sp in ss.get("spans", []):
                    status = sp.get("status") or {}
                    out.append(
                        {
                            "trace_id": _hex_id(sp.get("traceId"), 32),
                            "span_id": _hex_id(sp.get("spanId"), 16),
                            "parent_span_id": _hex_id(sp.get("parentSpanId"), 16),
                            "name": sp.get("name") or "unnamed",
                            "kind": int(sp.get("kind", 0) or 0),
                            "start_ns": int(sp.get("startTimeUnixNano", 0)),
                            "end_ns": int(sp.get("endTimeUnixNano", 0)),
                            "attributes": _attrs_json(sp.get("attributes", [])),
                            "status_code": int(status.get("code", 0) or 0),
                            "status_message": status.get("message") or "",
                            "events": [
                                {
                                    "name": e.get("name", ""),
                                    "attributes": _attrs_json(e.get("attributes", [])),
                                }
                                for e in sp.get("events", [])
                            ],
                            "resource": resource,
                            "scope": (ss.get("scope") or {}).get("name", ""),
                        }
                    )
    except (AttributeError, TypeError, ValueError) as exc:
        if isinstance(exc, OTLPDecodeError):
            raise
        raise OTLPDecodeError(f"malformed OTLP JSON: {exc}") from exc
    return out


def decode(body: bytes, content_type: str) -> list[dict[str, Any]]:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct == "application/x-protobuf":
        return _from_protobuf(body)
    if ct == "application/json":
        return _from_json(body)
    raise OTLPDecodeError("unsupported content type; use application/x-protobuf or application/json")


# --- Mapping ------------------------------------------------------------------


def _ns_to_dt(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1e9, tz=UTC)


def _first(attrs: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if attrs.get(k) not in (None, ""):
            return attrs[k]
    return None


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def classify(attrs: dict[str, Any], otel_kind: int) -> str:
    explicit = attrs.get("tracelens.span.kind")
    if isinstance(explicit, str) and explicit.lower() in VALID_KINDS:
        return explicit.lower()
    oi = attrs.get("openinference.span.kind")
    if isinstance(oi, str) and oi.upper() in OPENINFERENCE_KINDS:
        return OPENINFERENCE_KINDS[oi.upper()]
    op = attrs.get("gen_ai.operation.name")
    if op == "execute_tool":
        return "tool"
    if op in ("invoke_agent", "create_agent"):
        return "agent"
    if any(k.startswith("gen_ai.") for k in attrs) or "llm.model_name" in attrs:
        return "llm"
    if any(k in attrs for k in ("http.method", "http.request.method", "url.full", "http.url")):
        return "http"
    # SpanKind CLIENT (3) without other hints is most often an outbound call.
    return "other"


def _span_error(raw: dict[str, Any]) -> ErrorIn | None:
    for event in raw["events"]:
        if event["name"] == "exception":
            a = event["attributes"]
            return ErrorIn(
                type=str(a.get("exception.type") or "Exception")[:256],
                message=str(a.get("exception.message") or raw["status_message"] or "")[:8000] or None,
                stacktrace=str(a["exception.stacktrace"])[:32000] if a.get("exception.stacktrace") else None,
            )
    if raw["status_code"] == 2:
        return ErrorIn(type="SpanError", message=raw["status_message"] or None)
    return None


def to_batch(raw_spans: list[dict[str, Any]]) -> IngestBatch:
    if not raw_spans:
        raise OTLPDecodeError("request contains no spans")
    spans: list[SpanIn] = []
    traces: dict[str, TraceIn] = {}
    for raw in raw_spans:
        if not raw["trace_id"] or not raw["span_id"]:
            raise OTLPDecodeError("every span requires a non-zero traceId and spanId")
        attrs = dict(raw["attributes"])
        resource = raw["resource"]
        kind = classify(attrs, raw["kind"])
        input_tokens = _int(
            _first(attrs, "gen_ai.usage.input_tokens", "gen_ai.usage.prompt_tokens", "llm.token_count.prompt")
        )
        output_tokens = _int(
            _first(
                attrs,
                "gen_ai.usage.output_tokens",
                "gen_ai.usage.completion_tokens",
                "llm.token_count.completion",
            )
        )
        cached_tokens = _int(
            _first(attrs, "gen_ai.usage.cache_read_input_tokens", "llm.token_count.prompt_details.cache_read")
        )
        total_tokens = _int(_first(attrs, "llm.token_count.total"))
        usage = None
        if input_tokens is not None or output_tokens is not None or total_tokens is not None:
            usage = UsageIn(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens,
                total_tokens=total_tokens,
                source="reported",
            )
        status = {2: "error", 1: "ok"}.get(raw["status_code"], "unset")
        end_ns = raw["end_ns"] or None
        input_value = _first(attrs, "input.value", "gen_ai.prompt")
        output_value = _first(attrs, "output.value", "gen_ai.completion")
        span_attrs = {k: v for k, v in attrs.items() if k not in CONSUMED_ATTRIBUTES}
        if resource.get("service.name"):
            span_attrs.setdefault("service.name", resource["service.name"])
        if raw["scope"]:
            span_attrs.setdefault("otel.scope.name", raw["scope"])
        try:
            span = SpanIn(
                trace_id=raw["trace_id"],
                span_id=raw["span_id"],
                parent_span_id=raw["parent_span_id"],
                name=(raw["name"] or "unnamed")[:512],
                kind=kind,  # type: ignore[arg-type]
                status=status,  # type: ignore[arg-type]
                start_time=_ns_to_dt(raw["start_ns"]),
                end_time=_ns_to_dt(end_ns) if end_ns else None,
                provider=_first(attrs, "gen_ai.provider.name", "gen_ai.system", "llm.provider", "llm.system"),
                model=_first(attrs, "gen_ai.response.model", "gen_ai.request.model", "llm.model_name"),
                input=input_value,
                output=output_value,
                usage=usage,
                error=_span_error(raw),
                attributes=span_attrs,
            )
        except ValidationError as exc:
            raise OTLPDecodeError(f"span {raw['span_id']} is invalid: {exc.errors()[0]['msg']}") from exc
        spans.append(span)
        if raw["parent_span_id"] is None:
            env = _first(resource, "deployment.environment.name", "deployment.environment")
            traces[raw["trace_id"]] = TraceIn(
                trace_id=raw["trace_id"],
                name=span.name,
                status="error" if status == "error" else "ok",
                start_time=span.start_time,
                end_time=span.end_time,
                environment=str(env)[:128] if env else None,
                release=str(resource["service.version"])[:128] if resource.get("service.version") else None,
                error=span.error,
                metadata={k: v for k, v in resource.items() if k.startswith(("service.", "telemetry.sdk."))},
            )
    return IngestBatch(traces=list(traces.values()), spans=spans)
