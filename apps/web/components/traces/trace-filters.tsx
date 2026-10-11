"use client";

import { Search, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/overlays";
import { TRACE_RANGES } from "@/lib/trace-ranges";
import { cn } from "@/lib/utils";

const ANY = "__any";
const STATUSES = [
  { value: "error", label: "Error", dot: "bg-error" },
  { value: "ok", label: "OK", dot: "bg-ok" },
  { value: "incomplete", label: "Incomplete", dot: "bg-warn" },
] as const;

export function TraceFilters({ options }: { options: { environments: string[]; models: string[] } }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [pending, startTransition] = React.useTransition();
  const urlQ = params.get("q") ?? "";
  const [q, setQ] = React.useState(urlQ);
  const [syncedQ, setSyncedQ] = React.useState(urlQ);
  if (syncedQ !== urlQ) {
    setSyncedQ(urlQ);
    setQ(urlQ);
  }

  function update(mutate: (p: URLSearchParams) => void) {
    const next = new URLSearchParams(params.toString());
    mutate(next);
    next.delete("cursor");
    startTransition(() => router.push(`${pathname}?${next.toString()}`, { scroll: false }));
  }

  const statuses = params.getAll("status");
  const range = params.get("range") ?? "24h";
  const active =
    ["q", "status", "model", "environment", "tag", "user_id", "session_id", "min_duration_ms"].some((k) => params.has(k)) ||
    range !== "24h";

  return (
    <div className={cn("flex flex-col gap-2 transition-opacity", pending && "opacity-70")} aria-busy={pending}>
      <div className="flex flex-wrap items-center gap-2">
        <form
          role="search"
          className="relative min-w-56 flex-1"
          onSubmit={(e) => {
            e.preventDefault();
            update((p) => (q.trim() ? p.set("q", q.trim()) : p.delete("q")));
          }}
        >
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search name, trace ID, user, session, or error"
            aria-label="Search traces"
            className="pl-8"
          />
        </form>
        <div className="flex items-center gap-1" role="group" aria-label="Status">
          {STATUSES.map((s) => {
            const on = statuses.includes(s.value);
            return (
              <button
                key={s.value}
                type="button"
                aria-pressed={on}
                onClick={() =>
                  update((p) => {
                    const cur = p.getAll("status").filter((v) => v !== s.value);
                    p.delete("status");
                    for (const v of on ? cur : [...cur, s.value]) p.append("status", v);
                  })
                }
                className={cn(
                  "inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-xs transition-colors",
                  on
                    ? "border-accent/60 bg-accent-soft text-foreground"
                    : "border-border bg-surface text-muted-foreground hover:text-foreground",
                )}
              >
                <span className={cn("size-1.5 rounded-full", s.dot)} aria-hidden />
                {s.label}
              </button>
            );
          })}
        </div>
        <Select
          aria-label="Model"
          className="w-44"
          value={params.get("model") ?? ANY}
          onValueChange={(v) => update((p) => (v === ANY ? p.delete("model") : p.set("model", v)))}
          options={[{ value: ANY, label: "Any model" }, ...options.models.map((m) => ({ value: m, label: m }))]}
        />
        {options.environments.length ? (
          <Select
            aria-label="Environment"
            className="w-36"
            value={params.get("environment") ?? ANY}
            onValueChange={(v) => update((p) => (v === ANY ? p.delete("environment") : p.set("environment", v)))}
            options={[
              { value: ANY, label: "Any environment" },
              ...options.environments.map((m) => ({ value: m, label: m })),
            ]}
          />
        ) : null}
        <Select
          aria-label="Time range"
          className="w-32"
          value={range}
          onValueChange={(v) => update((p) => p.set("range", v))}
          options={TRACE_RANGES.map((r) => ({ value: r, label: r === "all" ? "All time" : `Last ${r}` }))}
        />
      </div>
      {active ? (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          {(["tag", "user_id", "session_id", "min_duration_ms"] as const).map((k) =>
            params.get(k) ? (
              <button
                key={k}
                type="button"
                onClick={() => update((p) => p.delete(k))}
                className="inline-flex items-center gap-1 rounded-sm border border-border bg-muted px-1.5 py-0.5 font-mono text-muted-foreground hover:text-foreground"
              >
                {k.replace("_ms", "").replace("_", " ")}: {params.get(k)}
                <X className="size-3" aria-label="Remove filter" />
              </button>
            ) : null,
          )}
          <Button variant="ghost" size="sm" onClick={() => startTransition(() => router.push(pathname, { scroll: false }))}>
            Clear filters
          </Button>
        </div>
      ) : null}
    </div>
  );
}
