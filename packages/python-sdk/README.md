# TraceLens Python SDK

Record traces from AI agents and LLM applications and send them to a TraceLens server.

```bash
pip install ./packages/python-sdk               # core
pip install "./packages/python-sdk[openai]"     # plus the OpenAI integration
```

```python
import tracelens

tracelens.init()  # reads TRACELENS_API_KEY and TRACELENS_BASE_URL


@tracelens.observe(kind="tool")
def lookup_order(order_id: str) -> dict:
    return {"id": order_id, "status": "shipped"}


with tracelens.trace("answer-question", user_id="user-123") as t:
    order = lookup_order("A-1001")
    t.set_output(f"Order is {order['status']}")

tracelens.flush()
```

See [`docs/sdk.md`](../../docs/sdk.md) for the full reference: configuration, sampling,
redaction, batching, prompts, evaluations, and the OpenAI, Anthropic, LangChain, and
LangGraph integrations.
