"use client";

import { KeyRound, Plus, TriangleAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";
import {
  createApiKey,
  deleteProject,
  deleteProviderCredential,
  revokeApiKey,
  saveProviderCredential,
  updateProject,
} from "@/app/actions";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/code-block";
import { Field, Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogTrigger, Select, Switch } from "@/components/ui/overlays";
import { Alert, Badge, EmptyState, Mono, Panel, PanelHeader } from "@/components/ui/primitives";
import type { ApiKey, ApiKeyCreated, Project, ProviderCredentials } from "@/lib/types";
import { formatDateTime, formatRelative } from "@/lib/utils";

function useSave() {
  const router = useRouter();
  const [pending, setPending] = React.useState(false);
  const save = async (changes: Parameters<typeof updateProject>[1], projectId: string, message = "Settings saved") => {
    setPending(true);
    const res = await updateProject(projectId, changes);
    setPending(false);
    if (!res.ok) {
      toast.error(res.error);
      return false;
    }
    toast.success(message);
    router.refresh();
    return true;
  };
  return { pending, save };
}

/* General ---------------------------------------------------------------- */

export function GeneralSection({ project, canUpdate }: { project: Project; canUpdate: boolean }) {
  const { pending, save } = useSave();
  const [name, setName] = React.useState(project.name);
  const [threshold, setThreshold] = React.useState(String(project.slow_span_threshold_ms));
  const dirty = name.trim() !== project.name || Number(threshold) !== project.slow_span_threshold_ms;
  const thresholdValid = Number.isInteger(Number(threshold)) && Number(threshold) >= 1 && Number(threshold) <= 3_600_000;

  return (
    <Panel id="general" className="scroll-mt-6">
      <PanelHeader title="General" />
      <form
        className="grid gap-4 p-4 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          void save({ name: name.trim(), slow_span_threshold_ms: Number(threshold) }, project.id);
        }}
      >
        <Field label="Project name" htmlFor="p-name">
          <Input id="p-name" value={name} maxLength={80} required disabled={!canUpdate} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field
          label="Slow span threshold (ms)"
          htmlFor="p-slow"
          hint="Diagnosis flags spans slower than this."
          error={thresholdValid ? undefined : "Enter a whole number between 1 and 3,600,000"}
        >
          <Input
            id="p-slow"
            inputMode="numeric"
            value={threshold}
            disabled={!canUpdate}
            aria-invalid={!thresholdValid}
            onChange={(e) => setThreshold(e.target.value.replace(/[^\d]/g, ""))}
            className="font-mono"
          />
        </Field>
        <div className="flex items-center justify-between gap-3 sm:col-span-2">
          <p className="text-xs text-muted-foreground">
            Project ID <Mono>{project.id}</Mono>
          </p>
          {canUpdate ? (
            <Button type="submit" variant="primary" loading={pending} disabled={!dirty || !thresholdValid || !name.trim()}>
              Save
            </Button>
          ) : null}
        </div>
      </form>
    </Panel>
  );
}

/* API keys --------------------------------------------------------------- */

function keyState(k: ApiKey): { label: string; tone: "ok" | "neutral" | "error" | "warn" } {
  if (k.revoked_at) return { label: "Revoked", tone: "neutral" };
  if (k.expires_at && Date.parse(k.expires_at) < Date.now()) return { label: "Expired", tone: "warn" };
  return { label: "Active", tone: "ok" };
}

function CreateKeyDialog({ projectId, autoOpen }: { projectId: string; autoOpen: boolean }) {
  const router = useRouter();
  const [open, setOpen] = React.useState(autoOpen);
  const [name, setName] = React.useState("");
  const [expiry, setExpiry] = React.useState("never");
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [created, setCreated] = React.useState<ApiKeyCreated | null>(null);
  const [confirmed, setConfirmed] = React.useState(false);

  function reset() {
    setName("");
    setExpiry("never");
    setError(null);
    setCreated(null);
    setConfirmed(false);
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && created && !confirmed) return;
        setOpen(next);
        if (!next) {
          if (created) router.refresh();
          reset();
        }
      }}
    >
      <DialogTrigger asChild>
        <Button variant="primary" size="sm">
          <Plus /> Create key
        </Button>
      </DialogTrigger>
      <DialogContent
        title={created ? "Copy your API key" : "Create API key"}
        description={created ? undefined : "Keys can send traces and read prompts and datasets for this project only."}
      >
        {created ? (
          <div className="grid gap-3">
            <Alert tone="warn" title="This is the only time the key is shown">
              TraceLens stores a hash, so the key cannot be recovered. Store it in your secret manager or a local{" "}
              <Mono>.env</Mono> file that is not committed.
            </Alert>
            <div className="flex items-center gap-2 rounded-md border border-border-strong bg-background px-3 py-2">
              <code className="min-w-0 flex-1 break-all font-mono text-[12.5px]" data-testid="api-key-secret">
                {created.secret}
              </code>
              <CopyButton value={created.secret} />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} className="accent-[var(--accent)]" />
              I have stored this key somewhere safe
            </label>
            <div className="flex justify-end">
              <Button
                variant="primary"
                disabled={!confirmed}
                onClick={() => {
                  setOpen(false);
                  router.refresh();
                  reset();
                }}
              >
                Done
              </Button>
            </div>
          </div>
        ) : (
          <form
            className="grid gap-3"
            onSubmit={async (e) => {
              e.preventDefault();
              setPending(true);
              setError(null);
              const res = await createApiKey(projectId, name.trim(), expiry === "never" ? undefined : Number(expiry));
              setPending(false);
              if (!res.ok) setError(res.error);
              else setCreated(res.data);
            }}
          >
            <Field label="Name" htmlFor="key-name" hint="Where the key will be used, for example production-worker.">
              <Input id="key-name" required maxLength={80} autoFocus value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="Expires" htmlFor="key-expiry">
              <Select
                id="key-expiry"
                value={expiry}
                onValueChange={setExpiry}
                options={[
                  { value: "never", label: "Never" },
                  { value: "30", label: "In 30 days" },
                  { value: "90", label: "In 90 days" },
                  { value: "365", label: "In 1 year" },
                ]}
              />
            </Field>
            {error ? <Alert tone="error">{error}</Alert> : null}
            <div className="flex justify-end">
              <Button type="submit" variant="primary" loading={pending} disabled={!name.trim()}>
                Create key
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function ApiKeysSection({ projectId, keys, autoOpen }: { projectId: string; keys: ApiKey[]; autoOpen: boolean }) {
  const router = useRouter();
  const [busy, setBusy] = React.useState<string | null>(null);

  async function revoke(k: ApiKey) {
    if (!window.confirm(`Revoke "${k.name}"? Applications using it will stop sending traces immediately.`)) return;
    setBusy(k.id);
    const res = await revokeApiKey(projectId, k.id);
    setBusy(null);
    if (!res.ok) toast.error(res.error);
    else {
      toast.success("Key revoked");
      router.refresh();
    }
  }

  return (
    <Panel id="api-keys" className="scroll-mt-6">
      <PanelHeader
        title="API keys"
        description="Used by the SDK and OTLP exporters. Send as Authorization: Bearer <key>."
        actions={<CreateKeyDialog projectId={projectId} autoOpen={autoOpen} />}
      />
      {keys.length === 0 ? (
        <EmptyState icon={<KeyRound />} title="No API keys">
          Create a key to start sending traces to this project.
        </EmptyState>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="px-4 py-2 font-medium">Name</th>
                <th className="px-4 py-2 font-medium">Key</th>
                <th className="hidden px-4 py-2 font-medium sm:table-cell">Last used</th>
                <th className="hidden px-4 py-2 font-medium md:table-cell">Expires</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => {
                const s = keyState(k);
                return (
                  <tr key={k.id} className="border-b border-border last:border-0">
                    <td className="px-4 py-2.5">
                      <span className="font-medium">{k.name}</span>
                      <span className="block text-xs text-muted-foreground" title={formatDateTime(k.created_at)}>
                        Created {formatRelative(k.created_at)}
                      </span>
                    </td>
                    <td className="px-4 py-2.5">
                      <Mono className="text-muted-foreground">{k.key_prefix}…</Mono>
                    </td>
                    <td className="hidden px-4 py-2.5 text-muted-foreground sm:table-cell">
                      {k.last_used_at ? formatRelative(k.last_used_at) : "Never"}
                    </td>
                    <td className="hidden px-4 py-2.5 text-muted-foreground md:table-cell">
                      {k.expires_at ? formatDateTime(k.expires_at) : "Never"}
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge tone={s.tone}>{s.label}</Badge>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      {!k.revoked_at ? (
                        <Button variant="ghost" size="sm" loading={busy === k.id} onClick={() => revoke(k)}>
                          Revoke
                        </Button>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

/* Privacy & retention ---------------------------------------------------- */

const RETENTION = ["7", "14", "30", "90", "180", "365"];

export function PrivacySection({ project, canUpdate }: { project: Project; canUpdate: boolean }) {
  const { pending, save } = useSave();
  const retentionOptions = RETENTION.includes(String(project.retention_days))
    ? RETENTION
    : [...RETENTION, String(project.retention_days)].sort((a, b) => Number(a) - Number(b));

  return (
    <Panel id="privacy" className="scroll-mt-6">
      <PanelHeader title="Privacy and retention" />
      <div className="divide-y divide-border">
        <div className="flex items-start justify-between gap-6 px-4 py-4">
          <div>
            <label htmlFor="capture" className="text-sm font-medium">
              Capture inputs and outputs
            </label>
            <p className="mt-1 max-w-[62ch] text-sm text-muted-foreground">
              When off, TraceLens discards prompts, completions, and tool payloads at ingestion and keeps only their
              shape (for example &ldquo;an object with 3 keys&rdquo;). Timing, tokens, cost, and errors are still recorded.
              Common secrets such as API keys and bearer tokens are redacted either way.
            </p>
          </div>
          <Switch
            id="capture"
            checked={project.capture_payloads}
            disabled={!canUpdate || pending}
            onCheckedChange={(v) =>
              void save({ capture_payloads: v }, project.id, v ? "Payload capture turned on" : "Payload capture turned off")
            }
          />
        </div>
        <div className="flex flex-wrap items-start justify-between gap-6 px-4 py-4">
          <div>
            <label htmlFor="retention" className="text-sm font-medium">
              Retention
            </label>
            <p className="mt-1 max-w-[62ch] text-sm text-muted-foreground">
              Traces older than this are deleted by the background worker, which runs hourly. Deleting a trace from its
              detail page removes it immediately.
            </p>
          </div>
          <Select
            id="retention"
            className="w-36"
            value={String(project.retention_days)}
            disabled={!canUpdate || pending}
            onValueChange={(v) => void save({ retention_days: Number(v) }, project.id, `Retention set to ${v} days`)}
            options={retentionOptions.map((d) => ({ value: d, label: `${d} days` }))}
          />
        </div>
      </div>
    </Panel>
  );
}

/* Providers -------------------------------------------------------------- */

const DEFAULT_MODELS = { openai: "gpt-4o-mini", anthropic: "claude-haiku-4-5" } as const;

export function ProvidersSection({
  projectId,
  data,
  canUpdate,
}: {
  projectId: string;
  data: ProviderCredentials;
  canUpdate: boolean;
}) {
  const router = useRouter();
  const [provider, setProvider] = React.useState<"openai" | "anthropic">("openai");
  const [key, setKey] = React.useState("");
  const [model, setModel] = React.useState<string>(DEFAULT_MODELS.openai);
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  return (
    <Panel id="providers" className="scroll-mt-6">
      <PanelHeader
        title="AI providers"
        description="Used for AI investigations and model-based evaluations. Keys are encrypted at rest and never sent to the browser."
      />
      <div className="space-y-4 p-4">
        {!data.encryption_available ? (
          <Alert tone="warn" title="Encryption key not configured">
            Set <Mono>INTEGRATION_ENCRYPTION_KEY</Mono> on the API server to store provider keys. See the README for how to
            generate one.
          </Alert>
        ) : null}
        <div className="rounded-md border border-border">
          {data.items.length ? (
            <ul className="divide-y divide-border">
              {data.items.map((c) => (
                <li key={c.provider} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
                  <span className="w-20 text-sm font-medium capitalize">{c.provider}</span>
                  <Mono className="text-muted-foreground">••••{c.secret_last4}</Mono>
                  <Mono className="text-muted-foreground">{c.default_model}</Mono>
                  <span className="text-xs text-muted-foreground">updated {formatRelative(c.updated_at)}</span>
                  {canUpdate ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="ml-auto"
                      onClick={async () => {
                        if (!window.confirm(`Remove the ${c.provider} key from this project?`)) return;
                        const res = await deleteProviderCredential(projectId, c.provider);
                        if (!res.ok) toast.error(res.error);
                        else {
                          toast.success("Key removed");
                          router.refresh();
                        }
                      }}
                    >
                      Remove
                    </Button>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="px-3 py-2.5 text-sm text-muted-foreground">
              No project keys.{" "}
              {data.server_fallback.configured
                ? `The server default (${data.server_fallback.provider}, ${data.server_fallback.model}) will be used.`
                : "No server default is configured either, so AI features are unavailable until you add one."}
            </p>
          )}
        </div>
        {canUpdate && data.encryption_available ? (
          <form
            className="grid gap-3 sm:grid-cols-[140px_minmax(0,1fr)_200px_auto] sm:items-end"
            onSubmit={async (e) => {
              e.preventDefault();
              setPending(true);
              setError(null);
              const res = await saveProviderCredential(projectId, provider, key.trim(), model.trim());
              setPending(false);
              if (!res.ok) {
                setError(res.error);
                return;
              }
              setKey("");
              toast.success(`${provider === "openai" ? "OpenAI" : "Anthropic"} key saved`);
              router.refresh();
            }}
          >
            <Field label="Provider" htmlFor="prov">
              <Select
                id="prov"
                value={provider}
                onValueChange={(v) => {
                  const p = v as "openai" | "anthropic";
                  setProvider(p);
                  setModel(DEFAULT_MODELS[p]);
                }}
                options={[
                  { value: "openai", label: "OpenAI" },
                  { value: "anthropic", label: "Anthropic" },
                ]}
              />
            </Field>
            <Field label="API key" htmlFor="prov-key">
              <Input
                id="prov-key"
                type="password"
                autoComplete="off"
                required
                minLength={8}
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder={provider === "openai" ? "sk-…" : "sk-ant-…"}
              />
            </Field>
            <Field label="Default model" htmlFor="prov-model">
              <Input id="prov-model" required value={model} onChange={(e) => setModel(e.target.value)} className="font-mono" />
            </Field>
            <Button type="submit" variant="secondary" loading={pending} disabled={key.trim().length < 8 || !model.trim()}>
              Save key
            </Button>
            {error ? <Alert tone="error" className="sm:col-span-4">{error}</Alert> : null}
          </form>
        ) : null}
      </div>
    </Panel>
  );
}

/* Danger zone ------------------------------------------------------------ */

export function DangerZone({ project }: { project: Project }) {
  const router = useRouter();
  const [confirm, setConfirm] = React.useState("");
  const [pending, setPending] = React.useState(false);
  return (
    <Panel id="danger" className="scroll-mt-6 border-error/40">
      <PanelHeader title="Delete project" description="Deletes all traces, spans, keys, datasets, runs, and prompts. This cannot be undone." />
      <Dialog onOpenChange={(o) => !o && setConfirm("")}>
        <div className="flex justify-end p-4">
          <DialogTrigger asChild>
            <Button variant="danger" size="sm">
              <TriangleAlert /> Delete project
            </Button>
          </DialogTrigger>
        </div>
        <DialogContent title={`Delete ${project.name}?`} description="All data in this project is removed immediately.">
          <form
            className="grid gap-3"
            onSubmit={async (e) => {
              e.preventDefault();
              setPending(true);
              const res = await deleteProject(project.id);
              setPending(false);
              if (!res.ok) {
                toast.error(res.error);
                return;
              }
              toast.success("Project deleted");
              router.push("/projects");
              router.refresh();
            }}
          >
            <Field label={`Type ${project.name} to confirm`} htmlFor="confirm-name">
              <Input id="confirm-name" autoComplete="off" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            </Field>
            <div className="flex justify-end">
              <Button type="submit" variant="danger" loading={pending} disabled={confirm !== project.name}>
                Delete permanently
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </Panel>
  );
}
