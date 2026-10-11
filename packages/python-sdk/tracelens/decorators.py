"""The ``@observe`` decorator."""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any, TypeVar, overload

from tracelens.tracing import SpanKind

F = TypeVar("F", bound=Callable[..., Any])


def _capture_args(sig: inspect.Signature | None, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    if sig is None:
        return {"args": list(args), "kwargs": kwargs}
    try:
        bound = sig.bind_partial(*args, **kwargs)
    except TypeError:
        return {"args": list(args), "kwargs": kwargs}
    values = dict(bound.arguments)
    for skip in ("self", "cls"):
        values.pop(skip, None)
    return values


@overload
def observe(func: F) -> F: ...


@overload
def observe(
    func: None = None,
    *,
    name: str | None = None,
    kind: SpanKind = "custom",
    capture_input: bool = True,
    capture_output: bool = True,
) -> Callable[[F], F]: ...


def observe(
    func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    kind: SpanKind = "custom",
    capture_input: bool = True,
    capture_output: bool = True,
) -> Any:
    """Record each call of the decorated function as a span.

    Works with sync and async functions and generators. Without an active trace, the
    call becomes the root span of a new trace. Exceptions are recorded and re-raised.
    """

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        span_name = name or getattr(fn, "__qualname__", getattr(fn, "__name__", "function"))
        try:
            sig: inspect.Signature | None = inspect.signature(fn)
        except (TypeError, ValueError):
            sig = None

        def start(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
            from tracelens.client import get_client

            span = get_client().span(span_name, kind)
            span.set_attribute("code.function", getattr(fn, "__qualname__", span_name))
            if capture_input:
                span.set_input(_capture_args(sig, args, kwargs))
            return span

        if inspect.isasyncgenfunction(fn):

            @functools.wraps(fn)
            async def agen_wrapper(*args: Any, **kwargs: Any) -> Any:
                span = start(args, kwargs)
                items: list[Any] = []
                with span:
                    async for item in fn(*args, **kwargs):
                        if capture_output and len(items) < 100:
                            items.append(item)
                        yield item
                    if capture_output:
                        span.set_output(items)

            return agen_wrapper

        if inspect.isgeneratorfunction(fn):

            @functools.wraps(fn)
            def gen_wrapper(*args: Any, **kwargs: Any) -> Any:
                span = start(args, kwargs)
                items: list[Any] = []
                with span:
                    for item in fn(*args, **kwargs):
                        if capture_output and len(items) < 100:
                            items.append(item)
                        yield item
                    if capture_output:
                        span.set_output(items)

            return gen_wrapper

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                span = start(args, kwargs)
                with span:
                    result = await fn(*args, **kwargs)
                    if capture_output:
                        span.set_output(result)
                    return result

            return async_wrapper

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            span = start(args, kwargs)
            with span:
                result = fn(*args, **kwargs)
                if capture_output:
                    span.set_output(result)
                return result

        return wrapper

    if func is not None:
        return decorate(func)
    return decorate
