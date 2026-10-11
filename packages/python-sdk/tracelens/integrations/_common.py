from __future__ import annotations

from typing import Any

from tracelens.client import get_client
from tracelens.tracing import Span

REQUEST_ATTRIBUTES = (
    "temperature",
    "top_p",
    "max_tokens",
    "max_completion_tokens",
    "max_output_tokens",
    "seed",
    "stop",
)


def get(obj: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a mapping or attribute-bearing object."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def start_llm_span(name: str, *, integration: str, provider: str, kwargs: dict[str, Any], input: Any) -> Span:
    attributes: dict[str, Any] = {"tracelens.integration": integration}
    for key in REQUEST_ATTRIBUTES:
        if kwargs.get(key) is not None:
            attributes[f"llm.request.{key}"] = kwargs[key]
    if kwargs.get("stream"):
        attributes["llm.request.stream"] = True
    if kwargs.get("tools"):
        attributes["llm.request.tools"] = [
            get(get(t, "function"), "name") or get(t, "name") for t in kwargs["tools"] if t is not None
        ]
    span = get_client().span(name, "llm", provider=provider, model=kwargs.get("model"), input=input)
    span.set_attributes(**attributes)
    return span
