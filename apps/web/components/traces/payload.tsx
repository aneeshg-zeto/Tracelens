"use client";

import * as React from "react";
import { CopyButton } from "@/components/ui/code-block";
import { cn } from "@/lib/utils";

const PREVIEW_CHARS = 6000;

type Message = { role: string; content: unknown; name?: string };

function asMessages(value: unknown): Message[] | null {
  const list = Array.isArray(value)
    ? value
    : value && typeof value === "object" && Array.isArray((value as { messages?: unknown }).messages)
      ? (value as { messages: unknown[] }).messages
      : null;
  if (!list?.length) return null;
  const ok = list.every(
    (m) => m && typeof m === "object" && typeof (m as Message).role === "string" && "content" in (m as object),
  );
  return ok ? (list as Message[]) : null;
}

function contentText(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    const texts = content.map((part) =>
      part && typeof part === "object" && typeof (part as { text?: unknown }).text === "string"
        ? (part as { text: string }).text
        : JSON.stringify(part, null, 2),
    );
    return texts.join("\n");
  }
  return JSON.stringify(content, null, 2);
}

function LongText({ text, className }: { text: string; className?: string }) {
  const [full, setFull] = React.useState(false);
  const long = text.length > PREVIEW_CHARS;
  return (
    <div>
      <pre className={cn("whitespace-pre-wrap break-words font-mono text-[12px] leading-5 text-foreground", className)}>
        {long && !full ? `${text.slice(0, PREVIEW_CHARS)}…` : text}
      </pre>
      {long ? (
        <button type="button" onClick={() => setFull((v) => !v)} className="mt-1 text-xs text-accent hover:underline">
          {full ? "Show less" : `Show all ${text.length.toLocaleString()} characters`}
        </button>
      ) : null}
    </div>
  );
}

const ROLE_TONE: Record<string, string> = {
  system: "text-info",
  user: "text-foreground",
  assistant: "text-accent",
  tool: "text-kind-tool",
};

export function Payload({ value, empty }: { value: unknown; empty: string }) {
  if (value === null || value === undefined || value === "") {
    return <p className="text-sm text-muted-foreground">{empty}</p>;
  }
  if (value && typeof value === "object" && (value as { _captured?: unknown })._captured === false) {
    const v = value as { type?: string; keys?: number; length?: number };
    const shape =
      v.type === "object" ? `an object with ${v.keys} keys` : v.type === "array" ? `a list of ${v.length} items` : v.type === "string" ? `a ${v.length}-character string` : `a ${v.type}`;
    return (
      <p className="text-sm text-muted-foreground">
        Not captured. Payload capture was off when this was ingested; TraceLens only recorded that it was {shape}.
      </p>
    );
  }
  if (value && typeof value === "object" && (value as { _truncated?: unknown })._truncated === true) {
    const v = value as { original_bytes?: number; preview?: string };
    return (
      <div className="space-y-2">
        <p className="text-xs text-warn">
          Truncated at ingestion: the original was {(v.original_bytes ?? 0).toLocaleString()} bytes. Showing the start.
        </p>
        <LongText text={v.preview ?? ""} />
      </div>
    );
  }
  const raw = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  const messages = asMessages(value);
  return (
    <div className="relative">
      <CopyButton value={raw} className="absolute right-0 top-0 z-10" />
      {messages ? (
        <ol className="space-y-2 pr-16">
          {messages.map((m, i) => (
            <li key={i} className="rounded-md border border-border bg-surface-2 px-3 py-2">
              <p className={cn("mb-1 font-mono text-[11px] font-medium uppercase tracking-wide", ROLE_TONE[m.role] ?? "text-muted-foreground")}>
                {m.role}
                {m.name ? <span className="ml-1 normal-case text-muted-foreground">({m.name})</span> : null}
              </p>
              <LongText text={contentText(m.content)} />
            </li>
          ))}
        </ol>
      ) : (
        <div className="pr-16">
          <LongText text={raw} />
        </div>
      )}
    </div>
  );
}
