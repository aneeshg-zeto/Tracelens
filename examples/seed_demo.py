"""Fill a project with a week of realistic, synthetic agent traces.

Useful for trying the dashboard before you instrument a real application. Every
trace is clearly tagged ``demo`` and generated locally; no model provider is called.

    export TRACELENS_API_KEY=tl_live_...
    export TRACELENS_BASE_URL=http://localhost:8000
    python examples/seed_demo.py --traces 300 --days 7

Requires only ``httpx``.
"""

from __future__ import annotations

import argparse
import os
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

MODELS = [
    ("openai", "gpt-4o-mini", 0.45),
    ("openai", "gpt-4.1", 0.2),
    ("anthropic", "claude-sonnet-4-20250514", 0.25),
    ("acme", "acme-local-7b", 0.1),  # deliberately missing from the pricing table
]
USERS = [f"user_{i:03d}" for i in range(1, 40)]
QUESTIONS = [
    "Where is my order #{n}?",
    "Can I get a refund for order #{n}?",
    "How do I change my shipping address?",
    "My discount code is not working",
    "Cancel my subscription please",
]


def iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat()


def pick_model(rng: random.Random) -> tuple[str, str]:
    r = rng.random()
    acc = 0.0
    for provider, model, weight in MODELS:
        acc += weight
        if r <= acc:
            return provider, model
    return MODELS[0][0], MODELS[0][1]


class Builder:
    def __init__(self, rng: random.Random, trace_id: str, start: datetime) -> None:
        self.rng = rng
        self.trace_id = trace_id
        self.cursor = start
        self.spans: list[dict[str, Any]] = []

    def span(self, name: str, kind: str, parent: str | None, ms: float, **extra: Any) -> dict[str, Any]:
        start = self.cursor
        end = start + timedelta(milliseconds=ms)
        span = {
            "trace_id": self.trace_id,
            "span_id": uuid.uuid4().hex[:16],
            "parent_span_id": parent,
            "name": name,
            "kind": kind,
            "start_time": iso(start),
            "end_time": iso(end),
            "status": "ok",
            **extra,
        }
        self.spans.append(span)
        self.cursor = end + timedelta(milliseconds=self.rng.uniform(1, 15))
        return span


def build_trace(rng: random.Random, start: datetime) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    trace_id = uuid.uuid4().hex
    b = Builder(rng, trace_id, start + timedelta(milliseconds=2))
    question = rng.choice(QUESTIONS).format(n=rng.randint(1000, 9999))
    provider, model = pick_model(rng)
    failure = rng.random()
    incomplete = failure > 0.985
    status = "ok"
    error: dict[str, Any] | None = None

    root = b.span("support-agent", "agent", None, 0)
    root_id = root["span_id"]
    b.cursor = start + timedelta(milliseconds=5)

    planner_in = rng.randint(300, 900)
    b.span(
        "plan",
        "llm",
        root_id,
        rng.uniform(250, 900),
        provider=provider,
        model=model,
        input={"messages": [{"role": "system", "content": "Plan the steps."}, {"role": "user", "content": question}]},
        output={"role": "assistant", "content": "1. search docs 2. look up order 3. answer"},
        usage={"input_tokens": planner_in, "output_tokens": rng.randint(20, 80)},
    )
    b.span(
        "search_docs",
        "retrieval",
        root_id,
        rng.uniform(40, 220),
        input={"query": question},
        output=[{"id": f"kb-{rng.randint(1, 80)}", "score": round(rng.uniform(0.4, 0.95), 2)} for _ in range(3)],
        attributes={"retrieval.top_k": 3, "vector_store": "pgvector"},
    )

    tool_parent = b.span("lookup_order", "tool", root_id, 0)
    attempts = 1 + (1 if failure > 0.8 else 0) + (1 if failure > 0.93 else 0)
    tool_ok = failure <= 0.93
    total_tool = 0.0
    for i in range(attempts):
        last = i == attempts - 1
        failed = not last or not tool_ok
        ms = rng.uniform(800, 1500) if failed else rng.uniform(60, 250)
        total_tool += ms
        s = b.span(
            "GET /orders/{id}",
            "http",
            tool_parent["span_id"],
            ms,
            attributes={"http.method": "GET", "http.status_code": 504 if failed else 200, "attempt": i + 1},
        )
        if failed:
            s["status"] = "error"
            s["error"] = {"type": "TimeoutError", "message": "orders-service did not respond within 800ms"}
    tool_parent["end_time"] = b.spans[-1]["end_time"]
    tool_parent["retry_count"] = attempts - 1
    if not tool_ok:
        tool_parent["status"] = "error"
        tool_parent["error"] = {"type": "ToolError", "message": "lookup_order failed after retries"}
        status = "error"
        error = {"type": "ToolError", "message": "lookup_order failed after retries"}

    if tool_ok and not incomplete:
        in_tok = rng.randint(800, 2600)
        answer_ms = rng.uniform(600, 2400) * (2.5 if model == "gpt-4.1" else 1)
        answer = b.span(
            "generate answer",
            "llm",
            root_id,
            answer_ms,
            provider=provider,
            model=model,
            input={"messages": [{"role": "user", "content": question}]},
            output={"role": "assistant", "content": "Your order shipped yesterday and arrives Thursday."},
            usage={"input_tokens": in_tok, "output_tokens": rng.randint(60, 400), "cached_tokens": rng.choice([0, 0, 512])},
            attributes={"llm.request.temperature": 0.2},
        )
        if failure > 0.9:
            answer["status"] = "error"
            answer["error"] = {"type": "RateLimitError", "message": "Rate limit reached for requests"}
            status = "error"
            error = answer["error"]

    end = b.spans[-1]["end_time"]
    root["end_time"] = None if incomplete else end
    root["status"] = "error" if status == "error" else "ok"
    if error:
        root["error"] = error
    trace = {
        "trace_id": trace_id,
        "name": "support-agent",
        "start_time": iso(start),
        "end_time": None if incomplete else end,
        "status": "incomplete" if incomplete else status,
        "environment": rng.choice(["production", "production", "production", "staging"]),
        "release": rng.choice(["2026.10.1", "2026.10.2"]),
        "user_id": rng.choice(USERS),
        "session_id": f"sess_{rng.randint(1, 120):04d}",
        "input": {"question": question},
        "output": None if status == "error" or incomplete else {"answer": "Your order shipped yesterday."},
        "error": error,
        "tags": ["demo", rng.choice(["web", "email", "chat"])],
        "metadata": {"seeded": True},
    }
    return trace, b.spans


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--traces", type=int, default=300)
    parser.add_argument("--days", type=float, default=7)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    api_key = os.environ.get("TRACELENS_API_KEY")
    base_url = os.environ.get("TRACELENS_BASE_URL", "http://localhost:8000").rstrip("/")
    if not api_key:
        raise SystemExit("Set TRACELENS_API_KEY to a project API key.")

    rng = random.Random(args.seed)
    now = datetime.now(UTC)
    starts = sorted(now - timedelta(days=args.days * rng.random() ** 1.6) for _ in range(args.traces))
    traces: list[dict[str, Any]] = []
    spans: list[dict[str, Any]] = []
    with httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=30) as client:

        def flush() -> None:
            if not traces:
                return
            res = client.post("/api/v1/ingest/batch", json={"traces": traces, "spans": spans})
            if res.status_code >= 400:
                raise SystemExit(f"Ingest failed ({res.status_code}): {res.text}")
            traces.clear()
            spans.clear()

        for start in starts:
            trace, trace_spans = build_trace(rng, start)
            traces.append(trace)
            spans.extend(trace_spans)
            if len(traces) >= 100:
                flush()
        flush()
    print(f"Sent {args.traces} demo traces to {base_url}")


if __name__ == "__main__":
    main()
