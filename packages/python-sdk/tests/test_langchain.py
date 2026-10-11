from __future__ import annotations

from typing import TypedDict

import pytest

pytest.importorskip("langchain_core")

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import tool

from tracelens.integrations.langchain import TraceLensCallbackHandler


def _model(text: str = "Paris is sunny.") -> FakeMessagesListChatModel:
    return FakeMessagesListChatModel(
        responses=[
            AIMessage(
                content=text,
                usage_metadata={"input_tokens": 21, "output_tokens": 5, "total_tokens": 26},
                response_metadata={"model_name": "fake-model-1", "finish_reason": "stop"},
            )
        ]
    )


class StaticRetriever(BaseRetriever):
    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        return [Document(page_content=f"doc about {query}", metadata={"source": "kb/1"})]


@tool
def get_weather(city: str) -> str:
    """Return the weather for a city."""
    return f"{city}: sunny"


def test_chain_produces_nested_spans_and_usage(tl, transport):
    chain = ChatPromptTemplate.from_messages([("human", "Weather in {city}?")]) | _model() | StrOutputParser()
    handler = TraceLensCallbackHandler(trace_name="weather-chain", user_id="u-7")
    result = chain.invoke({"city": "Paris"}, config={"callbacks": [handler]})
    assert result == "Paris is sunny."
    tl.flush()

    [trace] = transport.traces
    assert trace["name"] == "weather-chain" and trace["user_id"] == "u-7"
    assert trace["output"] == "Paris is sunny."
    root = transport.span("RunnableSequence")
    llm = transport.span("FakeMessagesListChatModel")
    assert root["parent_span_id"] is None and root["kind"] == "chain"
    assert llm["parent_span_id"] == root["span_id"]
    assert llm["kind"] == "llm"
    assert llm["usage"] == {"input_tokens": 21, "output_tokens": 5, "total_tokens": 26, "source": "reported"}
    assert llm["model"] == "fake-model-1"
    assert llm["input"]["messages"][0] == {"role": "user", "content": "Weather in Paris?"}
    assert llm["output"]["content"] == "Paris is sunny."
    assert all(s["attributes"]["tracelens.integration"] == "langchain" for s in transport.spans)
    assert {s["trace_id"] for s in transport.spans} == {trace["trace_id"]}


def test_tool_and_retriever_spans(tl, transport):
    handler = TraceLensCallbackHandler()
    with tl.trace("agent-run") as outer:
        assert get_weather.invoke({"city": "Oslo"}, config={"callbacks": [handler]}) == "Oslo: sunny"
        docs = StaticRetriever().invoke("refunds", config={"callbacks": [handler]})
    assert docs[0].page_content == "doc about refunds"
    tl.flush()
    tool_span = transport.span("get_weather")
    retr = transport.span("StaticRetriever")
    assert tool_span["kind"] == "tool" and tool_span["output"] == "Oslo: sunny"
    assert retr["kind"] == "retrieval"
    assert retr["input"] == {"query": "refunds"}
    assert retr["output"]["documents"][0]["metadata"] == {"source": "kb/1"}
    assert retr["attributes"]["retrieval.documents"] == 1
    # Runs inside an active TraceLens trace attach to it instead of starting new traces.
    assert tool_span["trace_id"] == retr["trace_id"] == outer.trace_id
    assert len(transport.traces) == 1


def test_chain_error_is_recorded(tl, transport):
    def explode(_: dict) -> str:
        raise RuntimeError("tool backend down")

    chain = RunnableLambda(explode, name="explode")
    with pytest.raises(RuntimeError):
        chain.invoke({}, config={"callbacks": [TraceLensCallbackHandler()]})
    tl.flush()
    span = transport.span("explode")
    assert span["status"] == "error" and span["error"]["message"] == "tool backend down"
    assert transport.traces[0]["status"] == "error"


async def test_async_chain(tl, transport):
    chain = ChatPromptTemplate.from_messages([("human", "{q}")]) | _model("ok") | StrOutputParser()
    assert await chain.ainvoke({"q": "hi"}, config={"callbacks": [TraceLensCallbackHandler()]}) == "ok"
    tl.flush()
    assert transport.span("FakeMessagesListChatModel")["usage"]["output_tokens"] == 5


langgraph = pytest.importorskip("langgraph")


class State(TypedDict, total=False):
    question: str
    context: str
    answer: str


def test_langgraph_nodes_become_agent_spans(tl, transport):
    from langgraph.graph import END, START, StateGraph

    from tracelens.integrations.langgraph import TraceLensCallbackHandler as GraphHandler

    def retrieve(state: State) -> State:
        return {"context": f"facts about {state['question']}"}

    def respond(state: State) -> State:
        return {"answer": f"Answer using {state['context']}"}

    builder = StateGraph(State)
    builder.add_node("retrieve", retrieve)
    builder.add_node("respond", respond)
    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "respond")
    builder.add_edge("respond", END)
    graph = builder.compile()

    result = graph.invoke(
        {"question": "refunds"}, config={"callbacks": [GraphHandler(trace_name="support-graph")]}
    )
    assert result["answer"] == "Answer using facts about refunds"
    tl.flush()

    [trace] = transport.traces
    assert trace["name"] == "support-graph"
    retrieve_span, respond_span = transport.span("retrieve"), transport.span("respond")
    assert retrieve_span["kind"] == "agent" and respond_span["kind"] == "agent"
    assert retrieve_span["attributes"]["langgraph.node"] == "retrieve"
    root = [s for s in transport.spans if s["parent_span_id"] is None]
    assert len(root) == 1
    assert retrieve_span["parent_span_id"] == root[0]["span_id"]
    assert all(s["attributes"]["tracelens.integration"] == "langgraph" for s in transport.spans)


def test_langchain_handler_detects_langgraph_runs(tl, transport):
    from langgraph.graph import END, START, StateGraph

    builder = StateGraph(State)
    builder.add_node("only", lambda s: {"answer": "x"})
    builder.add_edge(START, "only")
    builder.add_edge("only", END)
    builder.compile().invoke({"question": "q"}, config={"callbacks": [TraceLensCallbackHandler()]})
    tl.flush()
    assert transport.span("only")["attributes"]["tracelens.integration"] == "langgraph"
