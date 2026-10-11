"""OpenAI integration.

``instrument_openai(client)`` wraps ``chat.completions.create`` and ``responses.create`` on an
``OpenAI`` or ``AsyncOpenAI`` instance (including ``stream=True``) and records each call as an
LLM span with model, token usage, input messages, and output.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, TypeVar

from tracelens.integrations._common import get, start_llm_span
from tracelens.tracing import Span

C = TypeVar("C")
INTEGRATION = "openai"


def instrument_openai(client: C) -> C:
    """Instrument an OpenAI client instance in place and return it."""
    if getattr(client, "_tracelens_instrumented", False):
        return client
    completions = client.chat.completions  # type: ignore[attr-defined]
    completions.create = _wrap(completions.create, "chat")
    responses = getattr(client, "responses", None)
    if responses is not None and hasattr(responses, "create"):
        responses.create = _wrap(responses.create, "responses")
    client._tracelens_instrumented = True  # type: ignore[attr-defined]
    return client


def _input_for(endpoint: str, kwargs: dict[str, Any]) -> Any:
    if endpoint == "chat":
        return {"messages": kwargs.get("messages")}
    value: dict[str, Any] = {"input": kwargs.get("input")}
    if kwargs.get("instructions"):
        value["instructions"] = kwargs["instructions"]
    return value


def _apply_usage(span: Span, usage: Any) -> None:
    if usage is None:
        return
    input_tokens = get(usage, "prompt_tokens", get(usage, "input_tokens"))
    output_tokens = get(usage, "completion_tokens", get(usage, "output_tokens"))
    details = get(usage, "prompt_tokens_details") or get(usage, "input_tokens_details")
    span.set_usage(
        input_tokens,
        output_tokens,
        cached_tokens=get(details, "cached_tokens"),
        total_tokens=get(usage, "total_tokens"),
    )


def _finish_chat(span: Span, response: Any) -> None:
    span.set_model(get(response, "model"))
    choices = get(response, "choices") or []
    if choices:
        choice = choices[0]
        message = get(choice, "message")
        output: dict[str, Any] = {
            "role": get(message, "role", "assistant"),
            "content": get(message, "content"),
        }
        tool_calls = get(message, "tool_calls")
        if tool_calls:
            output["tool_calls"] = [
                {
                    "id": get(tc, "id"),
                    "name": get(get(tc, "function"), "name"),
                    "arguments": get(get(tc, "function"), "arguments"),
                }
                for tc in tool_calls
            ]
        span.set_output(output)
        if get(choice, "finish_reason"):
            span.set_attribute("llm.response.finish_reason", get(choice, "finish_reason"))
    _apply_usage(span, get(response, "usage"))
    if get(response, "id"):
        span.set_attribute("llm.response.id", get(response, "id"))


def _finish_responses(span: Span, response: Any) -> None:
    span.set_model(get(response, "model"))
    text = get(response, "output_text")
    if text is None:
        parts = []
        for item in get(response, "output") or []:
            for content in get(item, "content") or []:
                if get(content, "type") == "output_text":
                    parts.append(get(content, "text") or "")
        text = "".join(parts) if parts else None
    span.set_output({"role": "assistant", "content": text})
    _apply_usage(span, get(response, "usage"))
    if get(response, "status"):
        span.set_attribute("llm.response.status", get(response, "status"))
    if get(response, "id"):
        span.set_attribute("llm.response.id", get(response, "id"))


class _StreamState:
    def __init__(self, span: Span, endpoint: str) -> None:
        self.span = span
        self.endpoint = endpoint
        self.parts: list[str] = []
        self.finished = False

    def observe(self, event: Any) -> None:
        if self.endpoint == "chat":
            if get(event, "model"):
                self.span.set_model(get(event, "model"))
            for choice in get(event, "choices") or []:
                delta = get(choice, "delta")
                if get(delta, "content"):
                    self.parts.append(get(delta, "content"))
                if get(choice, "finish_reason"):
                    self.span.set_attribute("llm.response.finish_reason", get(choice, "finish_reason"))
            if get(event, "usage") is not None:
                _apply_usage(self.span, get(event, "usage"))
            return
        kind = get(event, "type")
        if kind == "response.output_text.delta":
            self.parts.append(get(event, "delta") or "")
        elif kind in ("response.completed", "response.incomplete", "response.failed"):
            response = get(event, "response")
            self.span.set_model(get(response, "model"))
            _apply_usage(self.span, get(response, "usage"))

    def finish(self, error: BaseException | None = None) -> None:
        if self.finished:
            return
        self.finished = True
        if error is not None:
            self.span.record_error(error)
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


def _wrap(original: Any, endpoint: str) -> Any:
    name = "openai.chat.completions" if endpoint == "chat" else "openai.responses"
    finish = _finish_chat if endpoint == "chat" else _finish_responses

    async def complete_async(awaitable: Any, span: Span, stream: bool) -> Any:
        try:
            response = await awaitable
        except BaseException as exc:
            span.record_error(exc)
            span.end()
            raise
        if stream:
            return _AsyncStream(response, _StreamState(span, endpoint))
        try:
            finish(span, response)
        finally:
            span.end()
        return response

    # The async client's create() is a plain function returning a coroutine, so detect
    # async calls by their result rather than by inspecting the function.
    @functools.wraps(original)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        span = start_llm_span(
            name,
            integration=INTEGRATION,
            provider="openai",
            kwargs=kwargs,
            input=_input_for(endpoint, kwargs),
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
            return _SyncStream(response, _StreamState(span, endpoint))
        try:
            finish(span, response)
        finally:
            span.end()
        return response

    return wrapper
