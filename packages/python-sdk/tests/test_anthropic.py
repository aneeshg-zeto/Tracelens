from __future__ import annotations

import json

import httpx
import pytest

anthropic = pytest.importorskip("anthropic")

import anthropic._base_client as _base  # noqa: E402

from tracelens.integrations.anthropic import instrument_anthropic  # noqa: E402

# Recent SDK releases moved to the httpx2 fork; build mock clients with whichever module the SDK uses.
hx = _base.__dict__.get("httpx2") or httpx

MESSAGE = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": "claude-3-5-haiku-20241022",
    "content": [{"type": "text", "text": "Hello!"}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 10, "output_tokens": 4, "cache_read_input_tokens": 3},
}

TOOL_MESSAGE = {
    **MESSAGE,
    "content": [
        {"type": "text", "text": "Checking."},
        {"type": "tool_use", "id": "tu_1", "name": "get_weather", "input": {"city": "Paris"}},
    ],
    "stop_reason": "tool_use",
}

STREAM_EVENTS = [
    (
        "message_start",
        {
            "type": "message_start",
            "message": {
                **MESSAGE,
                "content": [],
                "stop_reason": None,
                "usage": {"input_tokens": 10, "output_tokens": 1},
            },
        },
    ),
    (
        "content_block_start",
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    ),
    (
        "content_block_delta",
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hel"}},
    ),
    (
        "content_block_delta",
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "lo"}},
    ),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    (
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 5},
        },
    ),
    ("message_stop", {"type": "message_stop"}),
]


def _handler(request):
    body = json.loads(request.content)
    if body.get("model") == "broken":
        return hx.Response(
            429, json={"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}
        )
    if body.get("stream"):
        text = "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in STREAM_EVENTS)
        return hx.Response(200, content=text.encode(), headers={"content-type": "text/event-stream"})
    if body.get("tools"):
        return hx.Response(200, json=TOOL_MESSAGE)
    return hx.Response(200, json=MESSAGE)


def _client():
    return instrument_anthropic(
        anthropic.Anthropic(
            api_key="sk-ant-test", max_retries=0, http_client=hx.Client(transport=hx.MockTransport(_handler))
        )
    )


def test_messages_create(tl, transport):
    client = _client()
    with tl.trace("ask"):
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=100,
            system="Be nice",
            messages=[{"role": "user", "content": "Hi"}],
        )
    assert msg.content[0].text == "Hello!"
    tl.flush()
    span = transport.span("anthropic.messages")
    assert span["kind"] == "llm" and span["provider"] == "anthropic"
    assert span["model"] == "claude-3-5-haiku-20241022"
    assert span["usage"] == {"input_tokens": 10, "output_tokens": 4, "cached_tokens": 3, "source": "reported"}
    assert span["input"] == {"messages": [{"role": "user", "content": "Hi"}], "system": "Be nice"}
    assert span["output"] == {"role": "assistant", "content": "Hello!"}
    assert span["attributes"]["tracelens.integration"] == "anthropic"
    assert span["attributes"]["llm.request.max_tokens"] == 100
    assert span["attributes"]["llm.response.finish_reason"] == "end_turn"


def test_tool_use_blocks(tl, transport):
    client = _client()
    client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=100,
        messages=[{"role": "user", "content": "weather"}],
        tools=[
            {"name": "get_weather", "description": "d", "input_schema": {"type": "object", "properties": {}}}
        ],
    )
    tl.flush()
    span = transport.span("anthropic.messages")
    assert span["output"]["content"] == "Checking."
    assert span["output"]["tool_calls"] == [{"id": "tu_1", "name": "get_weather", "input": {"city": "Paris"}}]
    assert span["attributes"]["llm.request.tools"] == ["get_weather"]


def test_streaming(tl, transport):
    client = _client()
    stream = client.messages.create(
        model="claude-haiku-4-5", max_tokens=50, messages=[{"role": "user", "content": "Hi"}], stream=True
    )
    text = "".join(e.delta.text for e in stream if e.type == "content_block_delta")
    assert text == "Hello"
    tl.flush()
    span = transport.span("anthropic.messages")
    assert span["output"]["content"] == "Hello"
    assert span["usage"]["input_tokens"] == 10 and span["usage"]["output_tokens"] == 5
    assert span["attributes"]["llm.response.finish_reason"] == "end_turn"


def test_error_is_recorded(tl, transport):
    client = _client()
    with pytest.raises(anthropic.RateLimitError):
        client.messages.create(model="broken", max_tokens=10, messages=[{"role": "user", "content": "x"}])
    tl.flush()
    span = transport.span("anthropic.messages")
    assert span["status"] == "error" and span["error"]["type"] == "RateLimitError"


async def test_async_client(tl, transport):
    client = instrument_anthropic(
        anthropic.AsyncAnthropic(
            api_key="sk-ant-test",
            max_retries=0,
            http_client=hx.AsyncClient(transport=hx.MockTransport(_handler)),
        )
    )
    msg = await client.messages.create(
        model="claude-haiku-4-5", max_tokens=10, messages=[{"role": "user", "content": "Hi"}]
    )
    stream = await client.messages.create(
        model="claude-haiku-4-5", max_tokens=10, messages=[{"role": "user", "content": "Hi"}], stream=True
    )
    text = "".join([e.delta.text async for e in stream if e.type == "content_block_delta"])
    assert msg.content[0].text == "Hello!" and text == "Hello"
    tl.flush()
    assert [s["name"] for s in transport.spans] == ["anthropic.messages", "anthropic.messages"]
    assert all(s["usage"]["output_tokens"] in (4, 5) for s in transport.spans)
