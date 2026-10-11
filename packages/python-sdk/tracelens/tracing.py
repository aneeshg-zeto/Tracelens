"""Trace and span objects and context propagation."""

from __future__ import annotations

import secrets
import traceback
import uuid
from contextlib import suppress
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from tracelens.client import TraceLens
    from tracelens.prompts import Prompt

SpanKind = Literal["llm", "tool", "retrieval", "chain", "agent", "http", "custom", "other"]
SPAN_KINDS = frozenset({"llm", "tool", "retrieval", "chain", "agent", "http", "custom", "other"})

_current_trace: ContextVar[Trace | None] = ContextVar("tracelens_trace", default=None)
_current_span: ContextVar[Span | None] = ContextVar("tracelens_span", default=None)

_UNSET: Any = object()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_trace_id() -> str:
    return uuid.uuid4().hex


def new_span_id() -> str:
    return secrets.token_hex(8)


def current_trace() -> Trace | None:
    return _current_trace.get()


def current_span() -> Span | None:
    return _current_span.get()


def _error_dict(exc: BaseException) -> dict[str, Any]:
    return {
        "type": type(exc).__name__,
        "message": str(exc)[:8000],
        "stacktrace": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-32000:],
    }


class Trace:
    """One end-to-end run of an agent or application request."""

    def __init__(
        self,
        client: TraceLens,
        name: str,
        *,
        trace_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        environment: str | None = None,
        release: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        input: Any = None,
        sampled: bool = True,
    ) -> None:
        self._client = client
        self.trace_id = trace_id or new_trace_id()
        self.name = name or "trace"
        self.user_id = user_id
        self.session_id = session_id
        self.environment = environment if environment is not None else client.environment
        self.release = release if release is not None else client.release
        self.tags = list(tags or [])
        self.metadata = dict(metadata or {})
        self.input = input
        self.output: Any = None
        self.status: str = "ok"
        self.error: dict[str, Any] | None = None
        self.start_time = _now()
        self.end_time: datetime | None = None
        self.sampled = sampled
        self._tokens: list[tuple[Token[Any], Token[Any]]] = []

    # mutation helpers -------------------------------------------------------
    def set_input(self, value: Any) -> Trace:
        self.input = value
        return self

    def set_output(self, value: Any) -> Trace:
        self.output = value
        return self

    def set_user(self, user_id: str | None) -> Trace:
        self.user_id = user_id
        return self

    def set_session(self, session_id: str | None) -> Trace:
        self.session_id = session_id
        return self

    def set_metadata(self, **values: Any) -> Trace:
        self.metadata.update(values)
        return self

    def add_tags(self, *tags: str) -> Trace:
        self.tags.extend(t for t in tags if t and t not in self.tags)
        return self

    def record_error(self, exc: BaseException) -> Trace:
        self.status = "error"
        self.error = _error_dict(exc)
        return self

    def set_status(self, status: Literal["ok", "error"]) -> Trace:
        self.status = status
        return self

    # children ---------------------------------------------------------------
    def span(self, name: str, kind: SpanKind = "custom", **kwargs: Any) -> Span:
        parent = _current_span.get()
        if parent is not None and parent.trace is not self:
            parent = None
        return Span(self._client, self, name, kind=kind, parent=parent, **kwargs)

    # lifecycle --------------------------------------------------------------
    def end(self, output: Any = _UNSET) -> None:
        if self.end_time is not None:
            return
        if output is not _UNSET:
            self.output = output
        self.end_time = _now()
        if self.sampled:
            self._client._enqueue("trace", self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        payload, meta = self._client._encode_payload, self._client._encode_meta
        return {
            "trace_id": self.trace_id,
            "name": self.name[:512],
            "status": self.status,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "environment": self.environment,
            "release": self.release,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "input": payload(self.input),
            "output": payload(self.output),
            "error": self.error,
            "tags": self.tags[:50],
            "metadata": meta(self.metadata),
        }

    def __enter__(self) -> Trace:
        self._tokens.append((_current_trace.set(self), _current_span.set(None)))
        return self

    def __exit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> None:
        if exc is not None:
            self.record_error(exc)
        self.end()
        if self._tokens:
            t_token, s_token = self._tokens.pop()
            with suppress(ValueError):
                _current_span.reset(s_token)
                _current_trace.reset(t_token)

    async def __aenter__(self) -> Trace:
        return self.__enter__()

    async def __aexit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> None:
        self.__exit__(exc_type, exc, tb)


class Span:
    """A unit of work inside a trace: an LLM call, tool call, retrieval, or any custom step."""

    def __init__(
        self,
        client: TraceLens,
        trace: Trace,
        name: str,
        *,
        kind: SpanKind = "custom",
        parent: Span | None = None,
        input: Any = None,
        attributes: dict[str, Any] | None = None,
        provider: str | None = None,
        model: str | None = None,
        owns_trace: bool = False,
    ) -> None:
        self._client = client
        self.trace = trace
        self.span_id = new_span_id()
        self.parent_span_id = parent.span_id if parent is not None else None
        self.name = name or "span"
        self.kind: str = kind if kind in SPAN_KINDS else "other"
        self.input = input
        self.output: Any = None
        self.attributes: dict[str, Any] = dict(attributes or {})
        self.provider = provider
        self.model = model
        self.usage: dict[str, Any] | None = None
        self.cost_usd: float | None = None
        self.retry_count: int | None = None
        self.status: str = "ok"
        self.error: dict[str, Any] | None = None
        self.start_time = _now()
        self.end_time: datetime | None = None
        self._owns_trace = owns_trace
        self._tokens: list[tuple[Token[Any] | None, Token[Any]]] = []

    @property
    def trace_id(self) -> str:
        return self.trace.trace_id

    # mutation helpers -------------------------------------------------------
    def set_input(self, value: Any) -> Span:
        self.input = value
        return self

    def set_output(self, value: Any) -> Span:
        self.output = value
        return self

    def set_attribute(self, key: str, value: Any) -> Span:
        self.attributes[key] = value
        return self

    def set_attributes(self, **values: Any) -> Span:
        self.attributes.update(values)
        return self

    def set_model(self, model: str | None, provider: str | None = None) -> Span:
        if model:
            self.model = model
        if provider:
            self.provider = provider
        return self

    def set_usage(
        self,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        *,
        cached_tokens: int | None = None,
        total_tokens: int | None = None,
        estimated: bool = False,
    ) -> Span:
        usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_tokens": cached_tokens,
            "total_tokens": total_tokens,
            "source": "estimated" if estimated else "reported",
        }
        self.usage = {k: v for k, v in usage.items() if v is not None}
        return self

    def set_cost(self, usd: float) -> Span:
        self.cost_usd = usd
        return self

    def set_retry_count(self, count: int) -> Span:
        self.retry_count = count
        return self

    def set_prompt(self, prompt: Prompt) -> Span:
        """Link this span to a managed prompt version so it appears on the prompt's page."""
        self.attributes["tracelens.prompt.name"] = prompt.name
        self.attributes["tracelens.prompt.version"] = prompt.version
        return self

    def record_error(self, exc: BaseException) -> Span:
        self.status = "error"
        self.error = _error_dict(exc)
        return self

    def set_status(self, status: Literal["ok", "error"]) -> Span:
        self.status = status
        return self

    def span(self, name: str, kind: SpanKind = "custom", **kwargs: Any) -> Span:
        return Span(self._client, self.trace, name, kind=kind, parent=self, **kwargs)

    # lifecycle --------------------------------------------------------------
    def end(self, output: Any = _UNSET) -> None:
        if self.end_time is not None:
            return
        if output is not _UNSET:
            self.output = output
        self.end_time = _now()
        if self.trace.sampled:
            self._client._enqueue("span", self.to_dict())
        if self._owns_trace:
            if self.status == "error" and self.trace.status != "error":
                self.trace.status = "error"
                self.trace.error = self.error
            if self.trace.input is None:
                self.trace.input = self.input
            self.trace.end(self.output if self.trace.output is None else _UNSET)

    def to_dict(self) -> dict[str, Any]:
        payload, meta = self._client._encode_payload, self._client._encode_meta
        record: dict[str, Any] = {
            "trace_id": self.trace.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name[:512],
            "kind": self.kind,
            "status": self.status,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "provider": self.provider,
            "model": self.model,
            "input": payload(self.input),
            "output": payload(self.output),
            "usage": self.usage,
            "cost_usd": self.cost_usd,
            "error": self.error,
            "attributes": meta(self.attributes),
            "retry_count": self.retry_count,
        }
        return record

    def __enter__(self) -> Span:
        trace_token = _current_trace.set(self.trace) if _current_trace.get() is not self.trace else None
        self._tokens.append((trace_token, _current_span.set(self)))
        return self

    def __exit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> None:
        if exc is not None:
            self.record_error(exc)
        self.end()
        if self._tokens:
            trace_token, span_token = self._tokens.pop()
            # Generators resumed in another context cannot reset tokens created elsewhere.
            with suppress(ValueError):
                _current_span.reset(span_token)
                if trace_token is not None:
                    _current_trace.reset(trace_token)

    async def __aenter__(self) -> Span:
        return self.__enter__()

    async def __aexit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> None:
        self.__exit__(exc_type, exc, tb)
