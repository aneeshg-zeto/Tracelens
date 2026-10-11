"""TraceLens Python SDK.

Quick start::

    import tracelens

    tracelens.init()  # reads TRACELENS_API_KEY and TRACELENS_BASE_URL

    @tracelens.observe(kind="tool")
    def lookup(order_id: str) -> dict: ...

    with tracelens.trace("answer-question", user_id="u-1"):
        lookup("A-1001")

    tracelens.flush()
"""

from __future__ import annotations

from typing import Any

from tracelens.client import TraceLens, get_client, set_client
from tracelens.decorators import observe
from tracelens.prompts import Prompt
from tracelens.tracing import Span, SpanKind, Trace, current_span, current_trace
from tracelens.transport import TraceLensError
from tracelens.version import __version__

__all__ = [
    "Prompt",
    "Span",
    "SpanKind",
    "Trace",
    "TraceLens",
    "TraceLensError",
    "__version__",
    "current_span",
    "current_trace",
    "flush",
    "get_client",
    "get_prompt",
    "init",
    "observe",
    "run_evaluation",
    "set_client",
    "shutdown",
    "span",
    "trace",
]


def init(api_key: str | None = None, base_url: str | None = None, **kwargs: Any) -> TraceLens:
    """Create the global client. Arguments fall back to TRACELENS_* environment variables."""
    return TraceLens(api_key=api_key, base_url=base_url, set_global=True, **kwargs)


def trace(name: str, **kwargs: Any) -> Trace:
    return get_client().trace(name, **kwargs)


def span(name: str, kind: SpanKind = "custom", **kwargs: Any) -> Span:
    return get_client().span(name, kind, **kwargs)


def flush(timeout: float = 10.0) -> bool:
    return get_client().flush(timeout)


def shutdown(timeout: float = 10.0) -> None:
    get_client().shutdown(timeout)


def get_prompt(name: str, version: int | None = None, **kwargs: Any) -> Prompt:
    return get_client().get_prompt(name, version, **kwargs)


def run_evaluation(dataset: str, task: Any, evaluators: list[Any], **kwargs: Any) -> dict[str, Any]:
    return get_client().run_evaluation(dataset, task, evaluators, **kwargs)
