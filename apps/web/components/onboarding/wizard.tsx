"use client";

import { Check, CircleDashed, KeyRound, Loader2, Radio, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { createApiKey, createProject, sendTestTrace, updateOnboarding } from "@/app/actions";
import { Button } from "@/components/ui/button";
import { CodeBlock, CopyButton } from "@/components/ui/code-block";
import { Field, Input } from "@/components/ui/input";
import { Alert, Badge } from "@/components/ui/primitives";
import { authClient } from "@/lib/auth-client";
import { envSnippet, INTEGRATION_CHOICES, installSnippet, usageSnippet, type IntegrationId } from "@/lib/snippets";
import type { Onboarding } from "@/lib/types";
import { cn } from "@/lib/utils";

type Props = {
  userName: string;
  initial: Onboarding;
  activeOrg: { id: string; name: string } | null;
  projects: { id: string; name: string }[];
  canCreateProject: boolean;
  canCreateKey: boolean;
};

const STEP_TITLES: Record<string, string> = {
  organization: "Create an organization",
  project: "Create a project",
  integration: "Choose how you will send traces",
  "api-key": "Create an API key",
  install: "Install and configure",
  "test-trace": "Send a test trace",
};

function slugify(name: string) {
  const base = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 40);
  return `${base || "org"}-${Math.random().toString(36).slice(2, 6)}`;
}

export function OnboardingWizard({ userName, initial, activeOrg, projects, canCreateProject, canCreateKey }: Props) {
  const router = useRouter();
  const [state, setState] = React.useState(initial);
  const [secret, setSecret] = React.useState<string | null>(null);
  const done = new Set(state.completed_steps);
  if (activeOrg) done.add("organization");

  const projectId = state.project_id && projects.some((p) => p.id === state.project_id) ? state.project_id : null;
  const integration = (state.integration as IntegrationId | null) ?? null;

  const order = state.steps;
  const current =
    order.find((s) => {
      if (s === "organization") return !activeOrg;
      if (s === "project") return !projectId;
      if (s === "integration") return !integration;
      return !done.has(s);
    }) ?? null;

  async function save(changes: Parameters<typeof updateOnboarding>[0]) {
    const result = await updateOnboarding(changes);
    if (result.ok) setState(result.data);
    return result;
  }

  return (
    <ol className="mt-8 grid gap-3">
      {order.map((step, index) => {
        const isDone = step === "organization" ? !!activeOrg : step === "project" ? !!projectId : step === "integration" ? !!integration : done.has(step);
        const isCurrent = step === current;
        return (
          <li
            key={step}
            className={cn(
              "rounded-lg border bg-surface transition-colors",
              isCurrent ? "border-border-strong" : "border-border",
            )}
          >
            <div className="flex items-center gap-3 px-4 py-3">
              <span
                className={cn(
                  "grid size-6 shrink-0 place-items-center rounded-full border text-[11px] font-medium tabular",
                  isDone ? "border-ok/40 bg-ok-soft text-ok" : isCurrent ? "border-accent text-accent" : "border-border text-muted-foreground",
                )}
              >
                {isDone ? <Check className="size-3.5" /> : index + 1}
              </span>
              <h2 className={cn("text-sm font-medium", !isDone && !isCurrent && "text-muted-foreground")}>{STEP_TITLES[step]}</h2>
              {isDone && !isCurrent ? <StepSummary step={step} activeOrg={activeOrg} projects={projects} projectId={projectId} integration={integration} /> : null}
            </div>
            {isCurrent ? (
              <div className="border-t border-border px-4 py-4">
                {step === "organization" ? (
                  <OrganizationStep
                    userName={userName}
                    onCreated={async (orgId) => {
                      await save({ organization_id: orgId, complete_step: "organization" });
                      router.refresh();
                    }}
                  />
                ) : null}
                {step === "project" && activeOrg ? (
                  <ProjectStep
                    orgId={activeOrg.id}
                    projects={projects}
                    canCreate={canCreateProject}
                    onChosen={async (id) => {
                      await save({ organization_id: activeOrg.id, project_id: id, complete_step: "project" });
                      router.refresh();
                    }}
                  />
                ) : null}
                {step === "integration" ? (
                  <IntegrationStep onChosen={(id) => save({ integration: id, complete_step: "integration" })} />
                ) : null}
                {step === "api-key" && projectId ? (
                  <ApiKeyStep
                    projectId={projectId}
                    canCreate={canCreateKey}
                    secret={secret}
                    onCreated={setSecret}
                    onContinue={() => save({ complete_step: "api-key" })}
                  />
                ) : null}
                {step === "install" && integration ? (
                  <InstallStep integration={integration} secret={secret} onContinue={() => save({ complete_step: "install" })} />
                ) : null}
                {step === "test-trace" && projectId ? (
                  <TestTraceStep
                    projectId={projectId}
                    secret={secret}
                    firstTraceReceived={state.first_trace_received}
                    onFinished={async () => {
                      await save({ complete_step: "test-trace" });
                      router.push(`/p/${projectId}/traces`);
                    }}
                  />
                ) : null}
              </div>
            ) : null}
          </li>
        );
      })}
      {current === null && projectId ? (
        <li className="mt-2 flex items-center justify-between rounded-lg border border-ok/30 bg-ok-soft/40 px-4 py-3 text-sm">
          <span>Setup complete.</span>
          <Button asChild variant="primary" size="sm">
            <Link href={`/p/${projectId}`}>Open project</Link>
          </Button>
        </li>
      ) : null}
    </ol>
  );
}

function StepSummary({
  step,
  activeOrg,
  projects,
  projectId,
  integration,
}: {
  step: string;
  activeOrg: Props["activeOrg"];
  projects: Props["projects"];
  projectId: string | null;
  integration: IntegrationId | null;
}) {
  let text: string | null = null;
  if (step === "organization") text = activeOrg?.name ?? null;
  if (step === "project") text = projects.find((p) => p.id === projectId)?.name ?? null;
  if (step === "integration") text = INTEGRATION_CHOICES.find((i) => i.id === integration)?.name ?? null;
  return text ? <span className="ml-auto truncate text-xs text-muted-foreground">{text}</span> : null;
}

function OrganizationStep({ userName, onCreated }: { userName: string; onCreated: (orgId: string) => Promise<void> }) {
  const [name, setName] = React.useState(userName ? `${userName.split(" ")[0]}'s team` : "");
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  return (
    <form
      className="grid gap-3"
      onSubmit={async (e) => {
        e.preventDefault();
        setPending(true);
        setError(null);
        const { data, error } = await authClient.organization.create({ name: name.trim(), slug: slugify(name) });
        if (error || !data) {
          setError(error?.message ?? "Could not create the organization");
          setPending(false);
          return;
        }
        await authClient.organization.setActive({ organizationId: data.id });
        await onCreated(data.id);
        setPending(false);
      }}
    >
      <p className="text-sm text-muted-foreground">Organizations hold projects and members. You will be the owner.</p>
      <Field label="Organization name" htmlFor="org-name">
        <Input id="org-name" required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      {error ? <Alert tone="error">{error}</Alert> : null}
      <div>
        <Button type="submit" variant="primary" loading={pending} disabled={!name.trim()}>
          Create organization
        </Button>
      </div>
    </form>
  );
}

function ProjectStep({
  orgId,
  projects,
  canCreate,
  onChosen,
}: {
  orgId: string;
  projects: Props["projects"];
  canCreate: boolean;
  onChosen: (id: string) => Promise<void>;
}) {
  const [name, setName] = React.useState("");
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  return (
    <div className="grid gap-4">
      <p className="text-sm text-muted-foreground">
        A project groups the traces of one application or agent. Keys, privacy settings, and retention are per project.
      </p>
      {canCreate ? (
        <form
          className="grid gap-3"
          onSubmit={async (e) => {
            e.preventDefault();
            setPending(true);
            setError(null);
            const result = await createProject(orgId, name.trim());
            if (!result.ok) {
              setError(result.error);
              setPending(false);
              return;
            }
            await onChosen(result.data.id);
            setPending(false);
          }}
        >
          <Field label="Project name" htmlFor="project-name" hint="For example: support-agent, research-assistant.">
            <Input id="project-name" required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          {error ? <Alert tone="error">{error}</Alert> : null}
          <div>
            <Button type="submit" variant="primary" loading={pending} disabled={!name.trim()}>
              Create project
            </Button>
          </div>
        </form>
      ) : (
        <Alert tone="info">Your role cannot create projects. Choose an existing project or ask an admin.</Alert>
      )}
      {projects.length > 0 ? (
        <div>
          <p className="mb-2 text-xs text-muted-foreground">Or use an existing project</p>
          <div className="flex flex-wrap gap-2">
            {projects.map((p) => (
              <Button key={p.id} size="sm" variant="outline" onClick={() => onChosen(p.id)}>
                {p.name}
              </Button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function IntegrationStep({ onChosen }: { onChosen: (id: IntegrationId) => Promise<unknown> }) {
  const [pending, setPending] = React.useState<IntegrationId | null>(null);
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {INTEGRATION_CHOICES.map((choice) => (
        <button
          key={choice.id}
          type="button"
          disabled={pending !== null}
          onClick={async () => {
            setPending(choice.id);
            await onChosen(choice.id);
            setPending(null);
          }}
          className="flex items-start justify-between gap-3 rounded-md border border-border bg-surface-2/40 px-3 py-2.5 text-left transition-colors hover:border-accent/60 hover:bg-surface-2 disabled:opacity-60"
        >
          <span>
            <span className="block text-sm font-medium">{choice.name}</span>
            <span className="block text-xs text-muted-foreground">{choice.description}</span>
          </span>
          {pending === choice.id ? <Loader2 className="mt-0.5 size-4 animate-spin text-muted-foreground" /> : null}
        </button>
      ))}
    </div>
  );
}

function ApiKeyStep({
  projectId,
  canCreate,
  secret,
  onCreated,
  onContinue,
}: {
  projectId: string;
  canCreate: boolean;
  secret: string | null;
  onCreated: (secret: string) => void;
  onContinue: () => Promise<unknown>;
}) {
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [confirmed, setConfirmed] = React.useState(false);
  if (!canCreate) {
    return (
      <div className="grid gap-3">
        <Alert tone="info">Your role cannot create API keys. Ask an owner or admin for a project key, then continue.</Alert>
        <div>
          <Button variant="primary" onClick={() => onContinue()}>
            Continue
          </Button>
        </div>
      </div>
    );
  }
  if (secret) {
    return (
      <div className="grid gap-3">
        <Alert tone="warn" title="Copy this key now">
          This is the only time the full key is shown. TraceLens stores only a hash of it.
        </Alert>
        <div className="flex items-center gap-2 rounded-md border border-border-strong bg-background px-3 py-2">
          <KeyRound className="size-4 shrink-0 text-accent" />
          <code className="min-w-0 flex-1 break-all font-mono text-[12.5px]" data-testid="api-key-secret">
            {secret}
          </code>
          <CopyButton value={secret} />
        </div>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input type="checkbox" className="accent-[var(--accent)]" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          I saved this key somewhere safe
        </label>
        <div>
          <Button variant="primary" disabled={!confirmed} onClick={() => onContinue()}>
            Continue
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div className="grid gap-3">
      <p className="text-sm text-muted-foreground">
        Your application authenticates with a project API key. Keys can be revoked any time in project settings.
      </p>
      {error ? <Alert tone="error">{error}</Alert> : null}
      <div>
        <Button
          variant="primary"
          loading={pending}
          onClick={async () => {
            setPending(true);
            setError(null);
            const result = await createApiKey(projectId, "Onboarding key");
            setPending(false);
            if (!result.ok) setError(result.error);
            else onCreated(result.data.secret);
          }}
        >
          <KeyRound /> Create API key
        </Button>
      </div>
    </div>
  );
}

function InstallStep({
  integration,
  secret,
  onContinue,
}: {
  integration: IntegrationId;
  secret: string | null;
  onContinue: () => Promise<unknown>;
}) {
  const [pending, setPending] = React.useState(false);
  const install = installSnippet(integration);
  const envVars = envSnippet(secret ?? "tl_live_your_key");
  const usage = usageSnippet(integration);
  return (
    <div className="grid gap-4">
      <div className="grid gap-1.5">
        <p className="text-xs font-medium">1. Install</p>
        <CodeBlock code={install.code} language={install.language} />
        {integration !== "opentelemetry" ? (
          <p className="text-xs text-muted-foreground">
            Run from the TraceLens repository root. The SDK is not yet published to PyPI.
          </p>
        ) : null}
      </div>
      <div className="grid gap-1.5">
        <p className="text-xs font-medium">2. Configure</p>
        <CodeBlock code={envVars.code} language={envVars.language} />
      </div>
      <div className="grid gap-1.5">
        <p className="text-xs font-medium">3. Instrument</p>
        <CodeBlock code={usage.code} language={usage.language} />
      </div>
      <div>
        <Button
          variant="primary"
          loading={pending}
          onClick={async () => {
            setPending(true);
            await onContinue();
            setPending(false);
          }}
        >
          Continue
        </Button>
      </div>
    </div>
  );
}

function TestTraceStep({
  projectId,
  secret,
  firstTraceReceived,
  onFinished,
}: {
  projectId: string;
  secret: string | null;
  firstTraceReceived: boolean;
  onFinished: () => Promise<void>;
}) {
  const [key, setKey] = React.useState(secret ?? "");
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [sentId, setSentId] = React.useState<string | null>(null);
  const [received, setReceived] = React.useState(firstTraceReceived);

  React.useEffect(() => {
    if (received) return;
    const timer = setInterval(async () => {
      const res = await fetch("/api/backend/onboarding", { cache: "no-store" });
      if (res.ok) {
        const data = (await res.json()) as Onboarding;
        if (data.first_trace_received) setReceived(true);
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [received]);

  return (
    <div className="grid gap-4">
      <p className="text-sm text-muted-foreground">
        Send a trace from your code, or send a test trace now through the same ingestion API with your key.
      </p>
      <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
        <Field label="API key" htmlFor="test-key" hint={secret ? "Using the key you just created." : "Paste a key for this project."}>
          <Input
            id="test-key"
            type="password"
            autoComplete="off"
            placeholder="tl_live_…"
            value={key}
            onChange={(e) => setKey(e.target.value.trim())}
          />
        </Field>
        <Button
          variant="primary"
          loading={pending}
          disabled={!key.startsWith("tl_live_")}
          onClick={async () => {
            setPending(true);
            setError(null);
            const result = await sendTestTrace(projectId, key);
            setPending(false);
            if (!result.ok) setError(result.error);
            else {
              setSentId(result.data.trace_id);
              setReceived(true);
            }
          }}
        >
          <Radio /> Send test trace
        </Button>
      </div>
      {error ? (
        <Alert tone="error">
          <span className="inline-flex items-center gap-1.5">
            <TriangleAlert className="size-3.5" /> {error}
          </span>
        </Alert>
      ) : null}
      <div className="flex items-center gap-2 rounded-md border border-border bg-background px-3 py-2 text-sm">
        {received ? (
          <>
            <Check className="size-4 text-ok" />
            <span>Trace received.</span>
            {sentId ? (
              <Link href={`/p/${projectId}/traces/${encodeURIComponent(sentId)}`} className="ml-auto text-accent hover:underline">
                View trace
              </Link>
            ) : null}
          </>
        ) : (
          <>
            <CircleDashed className="size-4 animate-spin text-muted-foreground [animation-duration:3s]" />
            <span className="text-muted-foreground">Waiting for the first trace…</span>
            <Badge className="ml-auto">checking every 3s</Badge>
          </>
        )}
      </div>
      <div>
        <Button variant={received ? "primary" : "secondary"} disabled={!received} onClick={() => onFinished()}>
          Finish and open traces
        </Button>
      </div>
    </div>
  );
}
