from __future__ import annotations

import json

import httpx
import pytest

openai = pytest.importorskip("openai")

import openai._base_client as _base  # noqa: E402

from tracelens.integrations.openai import instrument_openai  # noqa: E402

# Recent SDK releases moved to the httpx2 fork; build mock clients with whichever module the SDK uses.
hx = _base.__dict__.get("httpx2") or httpx

CHAT_RESPONSE = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "created": 1,
    "model": "gpt-4o-mini-2024-07-18",
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "Hi there"}, "finish_reason": "stop"}
    ],
    "usage": {
        "prompt_tokens": 12,
        "completion_tokens": 3,
        "total_tokens": 15,
        "prompt_tokens_details": {"cached_tokens": 2},
    },
}

TOOL_RESPONSE = {
    **CHAT_RESPONSE,
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'},
                    }
                ],
            },
            "finish_reason": "tool_calls",
        }
    ],
}

RESPONSES_RESPONSE = {
    "id": "resp_1",
    "object": "response",
    "created_at": 1,
    "model": "gpt-4o-mini",
    "status": "completed",
    "output": [
        {
            "type": "message",
            "id": "msg_1",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Hello from responses", "annotations": []}],
        }
    ],
    "usage": {
        "input_tokens": 5,
        "output_tokens": 4,
        "total_tokens": 9,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 0},
    },
    "parallel_tool_calls": True,
    "tool_choice": "auto",
    "tools": [],
}


def _sse(chunks: list[dict]) -> bytes:
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return body.encode()


def _handler(request):
    body = json.loads(request.content)
    if request.url.path.endswith("/responses"):
        return hx.Response(200, json=RESPONSES_RESPONSE)
    if body.get("model") == "broken":
        return hx.Response(
            400,
            json={
                "error": {
                    "message": "model not found",
                    "type": "invalid_request_error",
                    "code": "model_not_found",
                }
            },
        )
    if body.get("stream"):
        base = {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4o-mini"}
        chunks = [
            {
                **base,
                "choices": [
                    {"index": 0, "delta": {"role": "assistant", "content": "Hel"}, "finish_reason": None}
                ],
            },
            {**base, "choices": [{"index": 0, "delta": {"content": "lo"}, "finish_reason": None}]},
            {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
            {**base, "choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}},
        ]
        return hx.Response(200, content=_sse(chunks), headers={"content-type": "text/event-stream"})
    if body.get("tools"):
        return hx.Response(200, json=TOOL_RESPONSE)
    return hx.Response(200, json=CHAT_RESPONSE)


def _client():
    return instrument_openai(
        openai.OpenAI(
            api_key="sk-test", max_retries=0, http_client=hx.Client(transport=hx.MockTransport(_handler))
        )
    )


def _async_client():
    return instrument_openai(
        openai.AsyncOpenAI(
            api_key="sk-test", max_retries=0, http_client=hx.AsyncClient(transport=hx.MockTransport(_handler))
        )
    )


def test_chat_completion_records_llm_span(tl, transport):
    client = _client()
    with tl.trace("ask"):
        result = client.chat.completions.create(
            model="gpt-4o-mini", messages=[{"role": "user", "content": "Hi"}], temperature=0.2
        )
    assert result.choices[0].message.content == "Hi there"
    tl.flush()
    span = transport.span("openai.chat.completions")
    assert span["kind"] == "llm"
    assert span["provider"] == "openai"
    assert span["model"] == "gpt-4o-mini-2024-07-18"
    assert span["usage"] == {
        "input_tokens": 12,
        "output_tokens": 3,
        "cached_tokens": 2,
        "total_tokens": 15,
        "source": "reported",
    }
    assert span["input"] == {"messages": [{"role": "user", "content": "Hi"}]}
    assert span["output"] == {"role": "assistant", "content": "Hi there"}
    assert span["attributes"]["tracelens.integration"] == "openai"
    assert span["attributes"]["llm.request.temperature"] == 0.2
    assert span["attributes"]["llm.response.finish_reason"] == "stop"
    assert span["trace_id"] == transport.traces[0]["trace_id"]


def test_tool_calls_are_captured(tl, transport):
    client = _client()
    tools = [
        {
            "type": "function",
            "function": {"name": "get_weather", "parameters": {"type": "object", "properties": {}}},
        }
    ]
    client.chat.completions.create(
        model="gpt-4o-mini", messages=[{"role": "user", "content": "weather?"}], tools=tools
    )
    tl.flush()
    span = transport.span("openai.chat.completions")
    assert span["output"]["tool_calls"] == [
        {"id": "call_1", "name": "get_weather", "arguments": '{"city":"Paris"}'}
    ]
    assert span["attributes"]["llm.request.tools"] == ["get_weather"]
    assert len(transport.traces) == 1  # implicit trace


def test_streaming_chat_completion(tl, transport):
    client = _client()
    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hi"}],
        stream=True,
        stream_options={"include_usage": True},
    )
    text = "".join((c.choices[0].delta.content or "") for c in stream if c.choices)
    assert text == "Hello"
    tl.flush()
    span = transport.span("openai.chat.completions")
    assert span["output"] == {"role": "assistant", "content": "Hello"}
    assert span["usage"]["input_tokens"] == 7 and span["usage"]["output_tokens"] == 2
    assert span["attributes"]["llm.request.stream"] is True


def test_responses_api(tl, transport):
    client = _client()
    response = client.responses.create(model="gpt-4o-mini", input="Say hello", instructions="Be brief")
    assert response.output_text == "Hello from responses"
    tl.flush()
    span = transport.span("openai.responses")
    assert span["output"] == {"role": "assistant", "content": "Hello from responses"}
    assert span["input"] == {"input": "Say hello", "instructions": "Be brief"}
    assert span["usage"]["input_tokens"] == 5 and span["usage"]["output_tokens"] == 4


def test_api_error_is_recorded_and_reraised(tl, transport):
    client = _client()
    with pytest.raises(openai.BadRequestError):
        client.chat.completions.create(model="broken", messages=[{"role": "user", "content": "x"}])
    tl.flush()
    span = transport.span("openai.chat.completions")
    assert span["status"] == "error"
    assert span["error"]["type"] == "BadRequestError"
    assert transport.traces[0]["status"] == "error"


async def test_async_client(tl, transport):
    client = _async_client()
    async with tl.trace("async-ask"):
        result = await client.chat.completions.create(
            model="gpt-4o-mini", messages=[{"role": "user", "content": "Hi"}]
        )
        stream = await client.chat.completions.create(
            model="gpt-4o-mini", messages=[{"role": "user", "content": "Hi"}], stream=True
        )
        parts = [c.choices[0].delta.content or "" async for c in stream if c.choices]
        response = await client.responses.create(model="gpt-4o-mini", input="hi")
    assert result.choices[0].message.content == "Hi there"
    assert "".join(parts) == "Hello"
    assert response.output_text == "Hello from responses"
    tl.flush()
    names = sorted(s["name"] for s in transport.spans)
    assert names == ["openai.chat.completions", "openai.chat.completions", "openai.responses"]
    assert {s["trace_id"] for s in transport.spans} == {transport.traces[0]["trace_id"]}


def test_instrument_is_idempotent(tl, transport):
    client = _client()
    instrument_openai(client)
    client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": "Hi"}])
    tl.flush()
    assert len(transport.spans) == 1
