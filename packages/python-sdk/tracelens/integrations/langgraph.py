"""LangGraph integration.

LangGraph runs on LangChain's callback system, so the same handler applies. This module sets
``tracelens.integration`` to ``langgraph`` for every span and records each graph node as an
``agent`` span::

    from tracelens.integrations.langgraph import TraceLensCallbackHandler

    graph.invoke(state, config={"callbacks": [TraceLensCallbackHandler(trace_name="support-graph")]})
"""

from __future__ import annotations

from typing import Any

from tracelens.integrations.langchain import TraceLensCallbackHandler as _LangChainHandler


class TraceLensCallbackHandler(_LangChainHandler):
    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("integration", "langgraph")
        super().__init__(**kwargs)


__all__ = ["TraceLensCallbackHandler"]
