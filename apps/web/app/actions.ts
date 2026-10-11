"use server";

import { revalidatePath } from "next/cache";
import { run, type ActionResult } from "@/lib/action-result";
import { api, ApiError } from "@/lib/api";
import { env } from "@/lib/env";
import type {
  ApiKey,
  ApiKeyCreated,
  Dataset,
  EvalRun,
  EvaluatorSpec,
  Example,
  Investigation,
  Onboarding,
  Project,
  PromptDetail,
} from "@/lib/types";

const enc = encodeURIComponent;

/* Projects & keys -------------------------------------------------------- */

export async function createProject(orgId: string, name: string): Promise<ActionResult<Project>> {
  return run(async () => {
    const project = await api<Project>(`/orgs/${enc(orgId)}/projects`, { method: "POST", body: { name } });
    revalidatePath("/projects");
    return project;
  });
}

export async function updateProject(
  projectId: string,
  changes: Partial<Pick<Project, "name" | "capture_payloads" | "retention_days" | "slow_span_threshold_ms">>,
): Promise<ActionResult<Project>> {
  return run(async () => {
    const project = await api<Project>(`/projects/${enc(projectId)}`, { method: "PATCH", body: changes });
    revalidatePath(`/p/${projectId}`, "layout");
    return project;
  });
}

export async function deleteProject(projectId: string): Promise<ActionResult> {
  return run(async () => {
    await api(`/projects/${enc(projectId)}`, { method: "DELETE" });
    revalidatePath("/projects");
    return undefined;
  });
}

export async function createApiKey(
  projectId: string,
  name: string,
  expiresInDays?: number,
): Promise<ActionResult<ApiKeyCreated>> {
  return run(() =>
    api<ApiKeyCreated>(`/projects/${enc(projectId)}/api-keys`, {
      method: "POST",
      body: { name, expires_in_days: expiresInDays || null },
    }),
  );
}

export async function revokeApiKey(projectId: string, keyId: string): Promise<ActionResult<ApiKey>> {
  return run(async () => {
    const key = await api<ApiKey>(`/projects/${enc(projectId)}/api-keys/${enc(keyId)}/revoke`, { method: "POST" });
    revalidatePath(`/p/${projectId}/settings`);
    return key;
  });
}

export async function saveProviderCredential(
  projectId: string,
  provider: "openai" | "anthropic",
  apiKey: string,
  defaultModel: string,
): Promise<ActionResult> {
  return run(async () => {
    await api(`/projects/${enc(projectId)}/provider-credentials/${provider}`, {
      method: "PUT",
      body: { api_key: apiKey, default_model: defaultModel },
    });
    revalidatePath(`/p/${projectId}/settings`);
    return undefined;
  });
}

export async function deleteProviderCredential(projectId: string, provider: "openai" | "anthropic"): Promise<ActionResult> {
  return run(async () => {
    await api(`/projects/${enc(projectId)}/provider-credentials/${provider}`, { method: "DELETE" });
    revalidatePath(`/p/${projectId}/settings`);
    return undefined;
  });
}

/* Onboarding ------------------------------------------------------------- */

export async function updateOnboarding(changes: {
  organization_id?: string;
  project_id?: string;
  integration?: string;
  complete_step?: string;
}): Promise<ActionResult<Onboarding>> {
  return run(() => api<Onboarding>("/onboarding", { method: "PUT", body: changes }));
}

/**
 * Sends a real trace through the public ingestion endpoint using the key the
 * user just created, so onboarding verifies the same path their app will use.
 */
export async function sendTestTrace(
  projectId: string,
  apiKey: string,
): Promise<ActionResult<{ trace_id: string }>> {
  return run(async () => {
    const base = env().TRACELENS_API_URL;
    const headers = { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" };
    const who = await fetch(`${base}/api/v1/ingest/whoami`, { headers, cache: "no-store" }).catch(() => null);
    if (!who) throw new ApiError(503, "api_unreachable", "The TraceLens API is unreachable. Check that it is running.");
    if (!who.ok) {
      throw who.status === 401
        ? new ApiError(401, "invalid_key", "The API key was rejected. Check that it was copied completely and has not been revoked.")
        : new ApiError(who.status, "ingest_error", `Key check failed (${who.status}).`);
    }
    const whoami = (await who.json()) as { project_id: string };
    if (whoami.project_id !== projectId) {
      throw new ApiError(400, "key_for_other_project", "This key belongs to a different project.");
    }

    const traceId = `onboarding-${crypto.randomUUID()}`;
    const t0 = Date.now() - 1800;
    const at = (ms: number) => new Date(t0 + ms).toISOString();
    const body = {
      traces: [
        {
          trace_id: traceId,
          name: "tracelens-test-trace",
          status: "ok",
          start_time: at(0),
          end_time: at(1500),
          environment: "onboarding",
          tags: ["test-trace"],
          metadata: { sent_from: "tracelens-onboarding" },
          input: { question: "Is my TraceLens setup working?" },
          output: { answer: "Yes. This trace was sent with your new API key." },
        },
      ],
      spans: [
        { trace_id: traceId, span_id: `${traceId}-root`, name: "test-agent", kind: "agent", start_time: at(0), end_time: at(1500) },
        {
          trace_id: traceId,
          span_id: `${traceId}-retrieve`,
          parent_span_id: `${traceId}-root`,
          name: "retrieve setup docs",
          kind: "retrieval",
          start_time: at(40),
          end_time: at(320),
        },
        {
          trace_id: traceId,
          span_id: `${traceId}-tool`,
          parent_span_id: `${traceId}-root`,
          name: "check_connection",
          kind: "tool",
          start_time: at(340),
          end_time: at(1460),
          attributes: { "tracelens.test": true, note: "No model was called; this trace contains no token usage." },
        },
      ],
    };
    const res = await fetch(`${base}/api/v1/ingest/batch`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      cache: "no-store",
    });
    if (!res.ok) {
      const data = await res.json().catch(() => null);
      throw new ApiError(res.status, data?.error?.code ?? "ingest_error", data?.error?.message ?? `Ingestion failed (${res.status}).`);
    }
    return { trace_id: traceId };
  });
}

/* Traces & investigations ------------------------------------------------- */

export async function deleteTrace(projectId: string, traceId: string): Promise<ActionResult> {
  return run(async () => {
    await api(`/projects/${enc(projectId)}/traces/${enc(traceId)}`, { method: "DELETE" });
    revalidatePath(`/p/${projectId}/traces`);
    return undefined;
  });
}

export async function startInvestigation(
  projectId: string,
  traceId: string,
  mode: "deterministic" | "ai",
  provider?: "openai" | "anthropic",
): Promise<ActionResult<Investigation>> {
  return run(() =>
    api<Investigation>(`/projects/${enc(projectId)}/traces/${enc(traceId)}/investigations`, {
      method: "POST",
      body: { mode, provider: provider ?? null },
    }),
  );
}

/* Evaluations ------------------------------------------------------------ */

export async function createDataset(projectId: string, name: string, description?: string): Promise<ActionResult<Dataset>> {
  return run(async () => {
    const ds = await api<Dataset>(`/projects/${enc(projectId)}/evaluations/datasets`, {
      method: "POST",
      body: { name, description: description || null },
    });
    revalidatePath(`/p/${projectId}/evaluations`);
    return ds;
  });
}

export async function deleteDataset(projectId: string, datasetId: string): Promise<ActionResult> {
  return run(async () => {
    await api(`/projects/${enc(projectId)}/evaluations/datasets/${enc(datasetId)}`, { method: "DELETE" });
    revalidatePath(`/p/${projectId}/evaluations`);
    return undefined;
  });
}

export async function addExamples(
  projectId: string,
  datasetId: string,
  examples: { input: unknown; expected_output?: unknown; metadata?: Record<string, unknown> }[],
): Promise<ActionResult<Example[]>> {
  return run(async () => {
    const rows = await api<Example[]>(`/projects/${enc(projectId)}/evaluations/datasets/${enc(datasetId)}/examples`, {
      method: "POST",
      body: { examples },
    });
    revalidatePath(`/p/${projectId}/evaluations/${datasetId}`);
    return rows;
  });
}

export async function deleteExample(projectId: string, datasetId: string, exampleId: string): Promise<ActionResult> {
  return run(async () => {
    await api(`/projects/${enc(projectId)}/evaluations/datasets/${enc(datasetId)}/examples/${enc(exampleId)}`, {
      method: "DELETE",
    });
    revalidatePath(`/p/${projectId}/evaluations/${datasetId}`);
    return undefined;
  });
}

export async function startModelRun(
  projectId: string,
  datasetId: string,
  body: {
    name: string;
    target: {
      type: "model";
      provider?: string | null;
      model?: string | null;
      system_prompt?: string | null;
      prompt_template: string;
      json_output: boolean;
      max_tokens: number;
    };
    evaluators: EvaluatorSpec[];
    acknowledge_external_calls: boolean;
  },
): Promise<ActionResult<EvalRun>> {
  return run(async () => {
    const r = await api<EvalRun>(`/projects/${enc(projectId)}/evaluations/datasets/${enc(datasetId)}/runs`, {
      method: "POST",
      body,
    });
    revalidatePath(`/p/${projectId}/evaluations/${datasetId}`);
    return r;
  });
}

/* Prompts ---------------------------------------------------------------- */

export async function createPrompt(
  projectId: string,
  body: { name: string; description?: string; content: string; notes?: string },
): Promise<ActionResult<PromptDetail>> {
  return run(async () => {
    const p = await api<PromptDetail>(`/projects/${enc(projectId)}/prompts`, { method: "POST", body });
    revalidatePath(`/p/${projectId}/prompts`);
    return p;
  });
}

export async function createPromptVersion(
  projectId: string,
  promptId: string,
  body: { content: string; notes?: string },
): Promise<ActionResult<PromptDetail>> {
  return run(() => api<PromptDetail>(`/projects/${enc(projectId)}/prompts/${enc(promptId)}/versions`, { method: "POST", body }));
}

export async function updatePromptVersion(
  projectId: string,
  promptId: string,
  version: number,
  body: { content?: string; notes?: string },
): Promise<ActionResult<PromptDetail>> {
  return run(() =>
    api<PromptDetail>(`/projects/${enc(projectId)}/prompts/${enc(promptId)}/versions/${version}`, { method: "PATCH", body }),
  );
}

export async function publishPromptVersion(
  projectId: string,
  promptId: string,
  version: number,
  activate: boolean,
): Promise<ActionResult<PromptDetail>> {
  return run(() =>
    api<PromptDetail>(`/projects/${enc(projectId)}/prompts/${enc(promptId)}/versions/${version}/publish`, {
      method: "POST",
      query: { activate },
    }),
  );
}

export async function activatePromptVersion(
  projectId: string,
  promptId: string,
  version: number,
): Promise<ActionResult<PromptDetail>> {
  return run(() =>
    api<PromptDetail>(`/projects/${enc(projectId)}/prompts/${enc(promptId)}/activate`, { method: "POST", body: { version } }),
  );
}
