"""LangChain integration.

Pass ``TraceLensCallbackHandler()`` in ``config={"callbacks": [...]}``. Chains, chat models and
LLMs, tools, and retrievers become spans with parent/child structure taken from LangChain's
run tree. Runs started inside an active TraceLens trace or span nest under it; otherwise the
outermost run starts a new trace. LangGraph graphs use the same callback system, and graph
nodes are recorded as ``agent`` spans.
"""

from __future__ import annotations

import threading
from typing import Any
from uuid import UUID

try:
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError as exc:  # pragma: no cover - exercised only without the extra installed
    raise ImportError(
        "TraceLensCallbackHandler requires langchain-core: pip install './packages/python-sdk[langchain]'"
    ) from exc

from tracelens.client import TraceLens, get_client
from tracelens.integrations._common import get
from tracelens.tracing import Span, Trace, current_span, current_trace

HIDDEN_TAG = "langsmith:hidden"


def _run_name(serialized: dict[str, Any] | None, kwargs: dict[str, Any], fallback: str) -> str:
    if kwargs.get("name"):
        return str(kwargs["name"])
    if serialized:
        if serialized.get("name"):
            return str(serialized["name"])
        ident = serialized.get("id")
        if isinstance(ident, list) and ident:
            return str(ident[-1])
    return fallback


def _message_dict(message: Any) -> dict[str, Any]:
    role = get(message, "type", "message")
    role = {"human": "user", "ai": "assistant"}.get(role, role)
    out: dict[str, Any] = {"role": role, "content": get(message, "content")}
    tool_calls = get(message, "tool_calls")
    if tool_calls:
        out["tool_calls"] = [
            {"id": get(t, "id"), "name": get(t, "name"), "args": get(t, "args")} for t in tool_calls
        ]
    return out


class TraceLensCallbackHandler(BaseCallbackHandler):
    """LangChain/LangGraph callback handler that records runs as TraceLens spans."""

    raise_error = False
    run_inline = True

    def __init__(
        self,
        *,
        client: TraceLens | None = None,
        trace_name: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        integration: str = "langchain",
    ) -> None:
        super().__init__()
        self._client = client
        self.trace_name = trace_name
        self.user_id = user_id
        self.session_id = session_id
        self.tags = list(tags or [])
        self.metadata = dict(metadata or {})
        self.integration = integration
        self._lock = threading.Lock()
        self._spans: dict[UUID, Span] = {}
        self._aliases: dict[UUID, UUID | None] = {}
        self._owned_traces: dict[UUID, Trace] = {}
        self._llm_params: dict[UUID, dict[str, Any]] = {}

    @property
    def client(self) -> TraceLens:
        return self._client or get_client()

    # helpers ----------------------------------------------------------------
    def _resolve_parent(self, parent_run_id: UUID | None) -> Span | None:
        seen = 0
        while parent_run_id is not None and seen < 100:
            seen += 1
            span = self._spans.get(parent_run_id)
            if span is not None:
                return span
            if parent_run_id in self._aliases:
                parent_run_id = self._aliases[parent_run_id]
                continue
            return None
        return None

    def _integration_for(self, metadata: dict[str, Any] | None, name: str) -> str:
        if self.integration == "langchain" and (
            (metadata and any(k.startswith("langgraph_") for k in metadata)) or name == "LangGraph"
        ):
            return "langgraph"
        return self.integration

    def _start(
        self,
        run_id: UUID,
        parent_run_id: UUID | None,
        name: str,
        kind: str,
        *,
        input: Any = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        with self._lock:
            if tags and HIDDEN_TAG in tags:
                self._aliases[run_id] = parent_run_id
                return
            parent = self._resolve_parent(parent_run_id)
            client = self.client
            attributes: dict[str, Any] = {"tracelens.integration": self._integration_for(metadata, name)}
            if tags:
                attributes["langchain.tags"] = [
                    t for t in tags if not t.startswith("seq:") and not t.startswith("graph:")
                ][:20]
            node = (metadata or {}).get("langgraph_node")
            if node:
                attributes["langgraph.node"] = node
                if (metadata or {}).get("langgraph_step") is not None:
                    attributes["langgraph.step"] = metadata["langgraph_step"]  # type: ignore[index]
            if parent is not None:
                span = parent.span(
                    name, kind, input=input, provider=provider, model=model, attributes=attributes
                )  # type: ignore[arg-type]
            else:
                outer_span = current_span()
                outer_trace = current_trace()
                if outer_span is not None:
                    span = outer_span.span(
                        name, kind, input=input, provider=provider, model=model, attributes=attributes
                    )  # type: ignore[arg-type]
                elif outer_trace is not None:
                    span = outer_trace.span(
                        name, kind, input=input, provider=provider, model=model, attributes=attributes
                    )  # type: ignore[arg-type]
                else:
                    trace = client.trace(
                        self.trace_name or name,
                        user_id=self.user_id,
                        session_id=self.session_id,
                        tags=self.tags,
                        metadata=self.metadata,
                        input=input,
                    )
                    span = trace.span(
                        name, kind, input=input, provider=provider, model=model, attributes=attributes
                    )  # type: ignore[arg-type]
                    self._owned_traces[run_id] = trace
            self._spans[run_id] = span

    def _end(self, run_id: UUID, *, output: Any = None, error: BaseException | None = None) -> Span | None:
        with self._lock:
            self._aliases.pop(run_id, None)
            span = self._spans.pop(run_id, None)
            trace = self._owned_traces.pop(run_id, None)
            self._llm_params.pop(run_id, None)
        if span is None:
            return None
        if error is not None:
            span.record_error(error)
        elif output is not None:
            span.set_output(output)
        span.end()
        if trace is not None:
            if error is not None:
                trace.record_error(error)
            trace.end(span.output)
        return span

    # chains -----------------------------------------------------------------
    def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        name = _run_name(serialized, kwargs, "chain")
        node = (metadata or {}).get("langgraph_node")
        kind = "agent" if node and node == name else "chain"
        self._start(run_id, parent_run_id, name, kind, input=inputs, tags=tags, metadata=metadata)

    def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._end(run_id, output=outputs)

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        if type(error).__name__ in ("GraphInterrupt", "ParentCommand"):
            self._end(run_id, output={"interrupted": True})
            return
        self._end(run_id, error=error)

    # models -----------------------------------------------------------------
    def _model_details(
        self, serialized: dict[str, Any] | None, metadata: dict[str, Any] | None, kwargs: dict[str, Any]
    ) -> tuple[str | None, str | None, dict[str, Any]]:
        params = kwargs.get("invocation_params") or {}
        meta = metadata or {}
        model = meta.get("ls_model_name") or params.get("model") or params.get("model_name")
        provider = meta.get("ls_provider") or params.get("_type")
        return provider, model, params

    def on_chat_model_start(
        self,
        serialized: dict[str, Any] | None,
        messages: list[list[Any]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        provider, model, params = self._model_details(serialized, metadata, kwargs)
        flat = [_message_dict(m) for batch in messages for m in batch]
        self._start(
            run_id,
            parent_run_id,
            _run_name(serialized, kwargs, "chat_model"),
            "llm",
            input={"messages": flat},
            tags=tags,
            metadata=metadata,
            provider=provider,
            model=model,
        )
        self._remember_params(run_id, params)

    def on_llm_start(
        self,
        serialized: dict[str, Any] | None,
        prompts: list[str],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        provider, model, params = self._model_details(serialized, metadata, kwargs)
        self._start(
            run_id,
            parent_run_id,
            _run_name(serialized, kwargs, "llm"),
            "llm",
            input={"prompts": prompts},
            tags=tags,
            metadata=metadata,
            provider=provider,
            model=model,
        )
        self._remember_params(run_id, params)

    def _remember_params(self, run_id: UUID, params: dict[str, Any]) -> None:
        with self._lock:
            span = self._spans.get(run_id)
            if span is None:
                return
            for key in ("temperature", "max_tokens", "top_p"):
                if params.get(key) is not None:
                    span.set_attribute(f"llm.request.{key}", params[key])

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        with self._lock:
            span = self._spans.get(run_id)
        if span is None:
            return
        generations = get(response, "generations") or []
        first = generations[0][0] if generations and generations[0] else None
        message = get(first, "message")
        output: Any = (
            _message_dict(message)
            if message is not None
            else {"role": "assistant", "content": get(first, "text")}
        )

        llm_output = get(response, "llm_output") or {}
        usage = (
            llm_output.get("token_usage") or llm_output.get("usage") if isinstance(llm_output, dict) else None
        )
        meta_usage = get(message, "usage_metadata")
        if meta_usage:
            details = get(meta_usage, "input_token_details") or {}
            span.set_usage(
                get(meta_usage, "input_tokens"),
                get(meta_usage, "output_tokens"),
                cached_tokens=get(details, "cache_read"),
                total_tokens=get(meta_usage, "total_tokens"),
            )
        elif usage:
            span.set_usage(
                get(usage, "prompt_tokens", get(usage, "input_tokens")),
                get(usage, "completion_tokens", get(usage, "output_tokens")),
                total_tokens=get(usage, "total_tokens"),
            )
        response_meta = get(message, "response_metadata") or {}
        model = (
            (llm_output.get("model_name") if isinstance(llm_output, dict) else None)
            or get(response_meta, "model_name")
            or get(response_meta, "model")
        )
        span.set_model(model)
        finish = get(response_meta, "finish_reason") or get(response_meta, "stop_reason")
        if finish:
            span.set_attribute("llm.response.finish_reason", finish)
        self._end(run_id, output=output)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._end(run_id, error=error)

    # tools ------------------------------------------------------------------
    def on_tool_start(
        self,
        serialized: dict[str, Any] | None,
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._start(
            run_id,
            parent_run_id,
            _run_name(serialized, kwargs, "tool"),
            "tool",
            input=inputs if inputs is not None else input_str,
            tags=tags,
            metadata=metadata,
        )

    def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        content = get(output, "content", output) if not isinstance(output, str | dict | list) else output
        self._end(run_id, output=content)

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._end(run_id, error=error)

    # retrievers -------------------------------------------------------------
    def on_retriever_start(
        self,
        serialized: dict[str, Any] | None,
        query: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._start(
            run_id,
            parent_run_id,
            _run_name(serialized, kwargs, "retriever"),
            "retrieval",
            input={"query": query},
            tags=tags,
            metadata=metadata,
        )

    def on_retriever_end(self, documents: Any, *, run_id: UUID, **kwargs: Any) -> None:
        docs = [
            {"content": get(d, "page_content"), "metadata": get(d, "metadata")} for d in (documents or [])
        ]
        with self._lock:
            span = self._spans.get(run_id)
        if span is not None:
            span.set_attribute("retrieval.documents", len(docs))
        self._end(run_id, output={"documents": docs})

    def on_retriever_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._end(run_id, error=error)
