import { ArrowRight, Boxes, FlaskConical, GitBranch, Lock, Search, Server } from "lucide-react";
import Link from "next/link";
import { Logo } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { getSession } from "@/lib/session";

const githubUrl = process.env.NEXT_PUBLIC_GITHUB_URL;
const docsUrl = process.env.NEXT_PUBLIC_DOCS_URL;

type DemoSpan = {
  name: string;
  kind: "agent" | "llm" | "tool" | "retrieval";
  depth: number;
  start: number;
  width: number;
  ms: string;
  error?: string;
};

// Synthetic example rendered with the same visual language as the real trace view.
const demo: DemoSpan[] = [
  { name: "support-agent", kind: "agent", depth: 0, start: 0, width: 100, ms: "4.82s" },
  { name: "retrieve policy docs", kind: "retrieval", depth: 1, start: 2, width: 14, ms: "671ms" },
  { name: "chat gpt-4o-mini", kind: "llm", depth: 1, start: 17, width: 21, ms: "1.01s" },
  { name: "lookup_order", kind: "tool", depth: 1, start: 39, width: 9, ms: "433ms" },
  { name: "refund_payment", kind: "tool", depth: 1, start: 49, width: 31, ms: "1.50s", error: "TimeoutError" },
  { name: "chat gpt-4o-mini", kind: "llm", depth: 1, start: 81, width: 18, ms: "868ms" },
];

const kindColor: Record<DemoSpan["kind"], string> = {
  agent: "bg-kind-agent",
  llm: "bg-kind-llm",
  tool: "bg-kind-tool",
  retrieval: "bg-kind-retrieval",
};

function DemoWaterfall() {
  return (
    <figure className="rounded-lg border border-border-strong bg-surface shadow-popover">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-2 text-xs">
          <span className="size-2 rounded-full bg-error" aria-hidden />
          <span className="font-medium text-foreground">refund-request</span>
          <span className="font-mono text-muted-foreground">4.82s · 6 spans · 2,914 tokens</span>
        </div>
        <span className="text-[11px] text-muted-foreground">Synthetic example</span>
      </div>
      <ol className="divide-y divide-border/60 py-1">
        {demo.map((s, i) => (
          <li key={i} className="grid grid-cols-[minmax(0,11rem)_1fr_3.5rem] items-center gap-3 px-4 py-1.5 sm:grid-cols-[minmax(0,14rem)_1fr_3.5rem]">
            <span className="flex min-w-0 items-center gap-1.5 text-xs" style={{ paddingLeft: s.depth * 14 }}>
              <span className={`size-1.5 shrink-0 rounded-[2px] ${kindColor[s.kind]}`} aria-hidden />
              <span className={`truncate ${s.error ? "text-error" : "text-foreground"}`}>{s.name}</span>
            </span>
            <span className="relative h-4">
              <span
                className={`absolute top-1 h-2 rounded-[2px] ${s.error ? "bg-error" : kindColor[s.kind]} ${s.depth === 0 ? "opacity-40" : ""}`}
                style={{ left: `${s.start}%`, width: `${s.width}%` }}
              />
            </span>
            <span className="text-right font-mono text-[11px] text-muted-foreground tabular">{s.ms}</span>
          </li>
        ))}
      </ol>
      <figcaption className="border-t border-border px-4 py-3 text-xs">
        <p className="font-medium text-error">refund_payment failed: TimeoutError</p>
        <p className="mt-1 text-muted-foreground">
          Deterministic diagnosis: the deepest failing span is a tool call that exceeded its timeout; the
          parent agent span inherited the error. Fix the tool timeout or add a retry with backoff.
        </p>
      </figcaption>
    </figure>
  );
}

const capabilities = [
  {
    icon: Search,
    title: "Trace explorer",
    body: "Filter by status, model, environment, user, or latency. Open any run as a span tree and waterfall with inputs, outputs, tokens, and cost per span.",
  },
  {
    icon: GitBranch,
    title: "Failure investigation",
    body: "Deterministic rules find the failing span, retry loops, timeouts, and latency outliers. Optional LLM analysis cites span IDs and separates facts from hypotheses.",
  },
  {
    icon: FlaskConical,
    title: "Evaluations",
    body: "Datasets, deterministic evaluators (exact, normalized, contains, JSON schema, fields), optional LLM judge labeled as probabilistic, and run-to-run comparison.",
  },
  {
    icon: Boxes,
    title: "Prompt versions",
    body: "Immutable published versions, rollback, and the traces that used each version.",
  },
  {
    icon: Lock,
    title: "Private by default",
    body: "Payload capture is off until you enable it per project. Secrets are redacted server-side. Keys are hashed and shown once. Retention runs automatically.",
  },
  {
    icon: Server,
    title: "Self-hosted",
    body: "Next.js, FastAPI, PostgreSQL, and Redis in one Docker Compose file. MIT licensed.",
  },
];

const snippet = `pip install ./packages/python-sdk

from tracelens import TraceLens, observe

tl = TraceLens(api_key="tl_live_…")

@observe(kind="tool")
def lookup_order(order_id: str): ...`;

export default async function LandingPage() {
  const session = await getSession();
  return (
    <div className="min-h-dvh">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <Logo />
        <nav className="flex items-center gap-1 text-sm">
          {docsUrl ? (
            <Button asChild variant="ghost" size="sm">
              <a href={docsUrl}>Docs</a>
            </Button>
          ) : null}
          {githubUrl ? (
            <Button asChild variant="ghost" size="sm">
              <a href={githubUrl}>GitHub</a>
            </Button>
          ) : null}
          {session ? (
            <Button asChild variant="primary" size="sm">
              <Link href="/projects">Open dashboard</Link>
            </Button>
          ) : (
            <>
              <Button asChild variant="ghost" size="sm">
                <Link href="/sign-in">Sign in</Link>
              </Button>
              <Button asChild variant="primary" size="sm">
                <Link href="/sign-up">Create account</Link>
              </Button>
            </>
          )}
        </nav>
      </header>

      <main>
        <section className="mx-auto grid max-w-6xl items-center gap-12 px-6 pb-20 pt-10 lg:grid-cols-[1fr_1.15fr] lg:pt-16">
          <div>
            <h1 className="max-w-[18ch] text-4xl font-semibold leading-[1.08] tracking-[-0.035em] text-foreground sm:text-5xl">
              See exactly where your agent went wrong.
            </h1>
            <p className="mt-5 max-w-[52ch] text-base leading-relaxed text-muted-foreground">
              TraceLens records every LLM call, tool call, and retrieval your agent makes, then points at the span
              that failed and explains why. Open source and self-hosted.
            </p>
            <div className="mt-7 flex flex-wrap items-center gap-3">
              <Button asChild variant="primary" size="lg">
                <Link href={session ? "/projects" : "/sign-up"}>
                  {session ? "Open dashboard" : "Start tracing"} <ArrowRight />
                </Link>
              </Button>
              <code className="rounded-md border border-border bg-surface px-3 py-2 font-mono text-xs text-muted-foreground">
                docker compose --profile app up
              </code>
            </div>
            <p className="mt-6 text-xs text-muted-foreground">
              Python SDK · OpenTelemetry (OTLP/HTTP) · OpenAI · Anthropic · LangChain · LangGraph
            </p>
          </div>
          <DemoWaterfall />
        </section>

        <section className="border-y border-border bg-surface/40">
          <div className="mx-auto grid max-w-6xl gap-10 px-6 py-16 lg:grid-cols-[1fr_1fr]">
            <div>
              <h2 className="text-2xl font-semibold tracking-[-0.025em]">Instrument in minutes</h2>
              <p className="mt-3 max-w-[56ch] text-sm leading-relaxed text-muted-foreground">
                Create a project, copy a key, and send your first trace from onboarding. Use the native SDK and its
                decorator, wrap your OpenAI or Anthropic client, attach the LangChain callback handler, or point any
                OpenTelemetry exporter at the OTLP endpoint.
              </p>
              <ul className="mt-6 space-y-2 text-sm">
                {[
                  "Batching, retries with backoff, and bounded queues: your app never blocks on TraceLens",
                  "Idempotent ingestion: retries and out-of-order spans produce the same trace",
                  "Token usage from the provider; cost from versioned list prices, or marked unavailable",
                ].map((line) => (
                  <li key={line} className="flex gap-2 text-muted-foreground">
                    <span className="mt-2 size-1 shrink-0 rounded-full bg-accent" aria-hidden />
                    {line}
                  </li>
                ))}
              </ul>
            </div>
            <pre className="overflow-x-auto rounded-lg border border-border bg-background p-5 font-mono text-[13px] leading-relaxed text-foreground">
              <code>{snippet}</code>
            </pre>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-6 py-16">
          <h2 className="text-2xl font-semibold tracking-[-0.025em]">Built for the debugging session</h2>
          <dl className="mt-8 grid gap-x-10 gap-y-8 sm:grid-cols-2 lg:grid-cols-3">
            {capabilities.map(({ icon: Icon, title, body }) => (
              <div key={title}>
                <dt className="flex items-center gap-2 text-sm font-medium text-foreground">
                  <Icon className="size-4 text-accent" aria-hidden />
                  {title}
                </dt>
                <dd className="mt-2 text-sm leading-relaxed text-muted-foreground">{body}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="mx-auto max-w-6xl px-6 pb-20">
          <div className="flex flex-col items-start justify-between gap-6 rounded-lg border border-border-strong bg-surface px-6 py-8 sm:flex-row sm:items-center">
            <div>
              <h2 className="text-xl font-semibold tracking-[-0.02em]">Your traces stay on your infrastructure.</h2>
              <p className="mt-1 text-sm text-muted-foreground">Run the whole stack locally with Docker Compose.</p>
            </div>
            <Button asChild variant="primary" size="lg">
              <Link href={session ? "/projects" : "/sign-up"}>
                {session ? "Open dashboard" : "Create an account"} <ArrowRight />
              </Link>
            </Button>
          </div>
        </section>
      </main>

      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-6 py-6 text-xs text-muted-foreground">
          <span>TraceLens · MIT License</span>
          <span>Self-hosted AI agent observability</span>
        </div>
      </footer>
    </div>
  );
}
