"""Send a small multi-step agent trace to TraceLens.

    pip install ./packages/python-sdk
    export TRACELENS_API_KEY=tl_live_...
    export TRACELENS_BASE_URL=http://localhost:8000
    python examples/quickstart.py

No LLM provider key is needed: the "model" here is a stub so you can see a full trace,
including a failing tool call that retries, without spending anything.
"""

from __future__ import annotations

import random
import time

import tracelens

tracelens.init(environment="example", release="quickstart-1")


@tracelens.observe(kind="retrieval")
def search_docs(query: str) -> list[dict]:
    time.sleep(0.05)
    return [{"id": "kb-12", "title": "Refund policy", "score": 0.91}, {"id": "kb-40", "title": "Shipping", "score": 0.55}]


@tracelens.observe(kind="tool")
def lookup_order(order_id: str, attempt: int) -> dict:
    time.sleep(0.03)
    if attempt == 0:
        raise TimeoutError("orders-service did not respond within 30ms")
    return {"id": order_id, "status": "delivered", "days_since_delivery": 12}


def call_model(question: str, context: list[dict], order: dict) -> str:
    with tracelens.span("generate answer", "llm", provider="openai", model="gpt-4o-mini") as span:
        span.set_input({"messages": [{"role": "system", "content": "You are a support agent."}, {"role": "user", "content": question}]})
        time.sleep(0.12)
        answer = f"Order {order['id']} was delivered {order['days_since_delivery']} days ago, so it is within the 30-day refund window."
        span.set_usage(input_tokens=420 + random.randint(0, 40), output_tokens=38)
        span.set_output({"role": "assistant", "content": answer})
        return answer


def main() -> None:
    question = "Can I still get a refund for order A-1001?"
    with tracelens.trace("support-agent", user_id="user-42", session_id="session-7", tags=["example"]) as trace:
        trace.set_input({"question": question})
        with tracelens.span("plan", "agent"):
            docs = search_docs(question)
            order: dict = {}
            for attempt in range(2):
                try:
                    order = lookup_order("A-1001", attempt)
                    break
                except TimeoutError:
                    continue
            answer = call_model(question, docs, order)
        trace.set_output({"answer": answer})
    tracelens.flush()
    print(f"Sent trace {trace.trace_id}")


if __name__ == "__main__":
    main()
