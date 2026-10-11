export const INGEST_URL = process.env.NEXT_PUBLIC_TRACELENS_INGEST_URL || "http://localhost:8000";

export type IntegrationId = "python-sdk" | "openai" | "anthropic" | "langchain" | "langgraph" | "opentelemetry";

export const INTEGRATION_CHOICES: { id: IntegrationId; name: string; description: string }[] = [
  { id: "python-sdk", name: "Python SDK", description: "Traces, spans, and the @observe decorator" },
  { id: "openai", name: "OpenAI", description: "Wrap an OpenAI client" },
  { id: "anthropic", name: "Anthropic", description: "Wrap an Anthropic client" },
  { id: "langchain", name: "LangChain", description: "Callback handler for chains and agents" },
  { id: "langgraph", name: "LangGraph", description: "Callback handler for graph runs" },
  { id: "opentelemetry", name: "OpenTelemetry", description: "Any OTLP/HTTP exporter" },
];

const env = (key: string) => `export TRACELENS_API_KEY="${key}"
export TRACELENS_BASE_URL="${INGEST_URL}"`;

export function installSnippet(integration: IntegrationId): { language: string; code: string } {
  switch (integration) {
    case "openai":
      return { language: "shell", code: `pip install "./packages/python-sdk[openai]"` };
    case "anthropic":
      return { language: "shell", code: `pip install "./packages/python-sdk[anthropic]"` };
    case "langchain":
      return { language: "shell", code: `pip install "./packages/python-sdk[langchain]"` };
    case "langgraph":
      return { language: "shell", code: `pip install "./packages/python-sdk[langgraph]"` };
    case "opentelemetry":
      return { language: "shell", code: "pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http" };
    default:
      return { language: "shell", code: "pip install ./packages/python-sdk" };
  }
}

export function envSnippet(key: string): { language: string; code: string } {
  return { language: "shell", code: env(key) };
}

export function usageSnippet(integration: IntegrationId): { language: string; code: string } {
  switch (integration) {
    case "openai":
      return {
        language: "python",
        code: `import tracelens
from openai import OpenAI
from tracelens.integrations.openai import instrument_openai

tracelens.init()  # reads TRACELENS_API_KEY and TRACELENS_BASE_URL
client = instrument_openai(OpenAI())

with tracelens.trace("answer-question", user_id="user-123"):
    client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello"}],
    )

tracelens.flush()`,
      };
    case "anthropic":
      return {
        language: "python",
        code: `import tracelens
from anthropic import Anthropic
from tracelens.integrations.anthropic import instrument_anthropic

tracelens.init()
client = instrument_anthropic(Anthropic())

with tracelens.trace("answer-question"):
    client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=256,
        messages=[{"role": "user", "content": "Hello"}],
    )

tracelens.flush()`,
      };
    case "langchain":
      return {
        language: "python",
        code: `import tracelens
from tracelens.integrations.langchain import TraceLensCallbackHandler

tracelens.init()
handler = TraceLensCallbackHandler()

result = chain.invoke({"question": "Hello"}, config={"callbacks": [handler]})
tracelens.flush()`,
      };
    case "langgraph":
      return {
        language: "python",
        code: `import tracelens
from tracelens.integrations.langgraph import TraceLensCallbackHandler

tracelens.init()
handler = TraceLensCallbackHandler(trace_name="support-graph")

graph = builder.compile()
graph.invoke({"messages": [("user", "Hello")]}, config={"callbacks": [handler]})
tracelens.flush()`,
      };
    case "opentelemetry":
      return {
        language: "python",
        code: `import os
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

exporter = OTLPSpanExporter(
    endpoint=os.environ["TRACELENS_BASE_URL"] + "/api/v1/otlp/v1/traces",
    headers={"Authorization": "Bearer " + os.environ["TRACELENS_API_KEY"]},
)
provider = TracerProvider(resource=Resource.create({"service.name": "my-agent"}))
provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(provider)

tracer = trace.get_tracer("my-agent")
with tracer.start_as_current_span("answer-question"):
    with tracer.start_as_current_span("chat gpt-4o-mini") as span:
        span.set_attribute("gen_ai.system", "openai")
        span.set_attribute("gen_ai.request.model", "gpt-4o-mini")

provider.shutdown()`,
      };
    default:
      return {
        language: "python",
        code: `import tracelens

tracelens.init()  # reads TRACELENS_API_KEY and TRACELENS_BASE_URL

@tracelens.observe(kind="tool")
def lookup_order(order_id: str) -> dict:
    return {"id": order_id, "status": "shipped"}

with tracelens.trace("answer-question", user_id="user-123") as t:
    order = lookup_order("A-1001")
    t.set_output({"answer": f"Order is {order['status']}"})

tracelens.flush()`,
      };
  }
}
