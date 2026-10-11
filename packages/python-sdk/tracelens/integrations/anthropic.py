"""Anthropic integration.

``instrument_anthropic(client)`` wraps ``messages.create`` on an ``Anthropic`` or
``AsyncAnthropic`` instance (including ``stream=True``) and records each call as an LLM span.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, TypeVar

from tracelens.integrations._common import get, start_llm_span
from tracelens.tracing import Span

C = TypeVar("C")
INTEGRATION = "anthropic"


def instrument_anthropic(client: C) -> C:
    """Instrument an Anthropic client instance in place and return it."""
    if getattr(client, "_tracelens_instrumented", False):
        return client
    messages = client.messages  # type: ignore[attr-defined]
    messages.create = _wrap(messages.create)
    client._tracelens_instrumented = True  # type: ignore[attr-defined]
    return client


def _input(kwargs: dict[str, Any]) -> Any:
    value: dict[str, Any] = {"messages": kwargs.get("messages")}
    if kwargs.get("system"):
        value["system"] = kwargs["system"]
    return value


def _apply_usage(span: Span, usage: Any, existing_input: int | None = None) -> None:
    if usage is None:
        return
    input_tokens = get(usage, "input_tokens")
    if input_tokens is None:
        input_tokens = existing_input
    span.set_usage(
        input_tokens,
        get(usage, "output_tokens"),
        cached_tokens=get(usage, "cache_read_input_tokens"),
    )


def _output(content: Any) -> dict[str, Any]:
    texts: list[str] = []
    tool_uses: list[dict[str, Any]] = []
    for block in content or []:
        kind = get(block, "type")
        if kind == "text":
            texts.append(get(block, "text") or "")
        elif kind == "tool_use":
            tool_uses.append(
                {"id": get(block, "id"), "name": get(block, "name"), "input": get(block, "input")}
            )
    output: dict[str, Any] = {"role": "assistant", "content": "".join(texts)}
    if tool_uses:
        output["tool_calls"] = tool_uses
    return output


def _finish(span: Span, response: Any) -> None:
    span.set_model(get(response, "model"))
    span.set_output(_output(get(response, "content")))
    _apply_usage(span, get(response, "usage"))
    if get(response, "stop_reason"):
        span.set_attribute("llm.response.finish_reason", get(response, "stop_reason"))
    if get(response, "id"):
        span.set_attribute("llm.response.id", get(response, "id"))


class _StreamState:
    def __init__(self, span: Span) -> None:
        self.span = span
        self.parts: list[str] = []
        self.input_tokens: int | None = None
        self.cached_tokens: int | None = None
        self.output_tokens: int | None = None
        self.finished = False

    def observe(self, event: Any) -> None:
        kind = get(event, "type")
        if kind == "message_start":
            message = get(event, "message")
            self.span.set_model(get(message, "model"))
            usage = get(message, "usage")
            self.input_tokens = get(usage, "input_tokens")
            self.cached_tokens = get(usage, "cache_read_input_tokens")
            self.output_tokens = get(usage, "output_tokens")
        elif kind == "content_block_delta":
            delta = get(event, "delta")
            if get(delta, "type") == "text_delta":
                self.parts.append(get(delta, "text") or "")
        elif kind == "message_delta":
            usage = get(event, "usage")
            if get(usage, "output_tokens") is not None:
                self.output_tokens = get(usage, "output_tokens")
            if get(usage, "input_tokens") is not None:
                self.input_tokens = get(usage, "input_tokens")
            stop = get(get(event, "delta"), "stop_reason")
            if stop:
                self.span.set_attribute("llm.response.finish_reason", stop)

    def finish(self, error: BaseException | None = None) -> None:
        if self.finished:
            return
        self.finished = True
        if error is not None:
            self.span.record_error(error)
        if self.input_tokens is not None or self.output_tokens is not None:
            self.span.set_usage(self.input_tokens, self.output_tokens, cached_tokens=self.cached_tokens)
        self.span.set_output({"role": "assistant", "content": "".join(self.parts)})
        self.span.end()


class _SyncStream:
    def __init__(self, stream: Any, state: _StreamState) -> None:
        self._stream = stream
        self._state = state

    def __iter__(self) -> Any:
        try:
            for event in self._stream:
                self._state.observe(event)
                yield event
        except BaseException as exc:
            self._state.finish(exc)
            raise
        self._state.finish()

    def __enter__(self) -> _SyncStream:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        close = getattr(self._stream, "close", None)
        if callable(close):
            close()
        self._state.finish()

    def __getattr__(self, item: str) -> Any:
        return getattr(self._stream, item)


class _AsyncStream:
    def __init__(self, stream: Any, state: _StreamState) -> None:
        self._stream = stream
        self._state = state

    async def __aiter__(self) -> Any:
        try:
            async for event in self._stream:
                self._state.observe(event)
                yield event
        except BaseException as exc:
            self._state.finish(exc)
            raise
        self._state.finish()

    async def __aenter__(self) -> _AsyncStream:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def close(self) -> None:
        close = getattr(self._stream, "close", None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result
        self._state.finish()

    def __getattr__(self, item: str) -> Any:
        return getattr(self._stream, item)


def _wrap(original: Any) -> Any:
    name = "anthropic.messages"

    async def complete_async(awaitable: Any, span: Span, stream: bool) -> Any:
        try:
            response = await awaitable
        except BaseException as exc:
            span.record_error(exc)
            span.end()
            raise
        if stream:
            return _AsyncStream(response, _StreamState(span))
        try:
            _finish(span, response)
        finally:
            span.end()
        return response

    # The async client's create() may be a plain function returning a coroutine, so detect
    # async calls by their result rather than by inspecting the function.
    @functools.wraps(original)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        span = start_llm_span(
            name, integration=INTEGRATION, provider="anthropic", kwargs=kwargs, input=_input(kwargs)
        )
        try:
            response = original(*args, **kwargs)
        except BaseException as exc:
            span.record_error(exc)
            span.end()
            raise
        stream = bool(kwargs.get("stream"))
        if inspect.isawaitable(response):
            return complete_async(response, span, stream)
        if stream:
            return _SyncStream(response, _StreamState(span))
        try:
            _finish(span, response)
        finally:
            span.end()
        return response

    return wrapper
