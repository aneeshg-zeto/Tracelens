export type Permissions = Record<string, string[]>;

export type Project = {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  capture_payloads: boolean;
  retention_days: number;
  slow_span_threshold_ms: number;
  created_at: string;
};

export type ProjectListItem = Project & { last_trace_at: string | null; trace_count: number };
export type ProjectList = { role: string; permissions: Permissions; items: ProjectListItem[] };
export type ProjectDetail = { project: Project; role: string; permissions: Permissions };

export type ApiKey = {
  id: string;
  name: string;
  key_prefix: string;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
};
export type ApiKeyCreated = ApiKey & { secret: string };

export type TraceStatus = "ok" | "error" | "incomplete";
export type SpanKind = "llm" | "tool" | "retrieval" | "chain" | "agent" | "http" | "custom" | "other";

export type TraceSummary = {
  id: string;
  trace_id: string;
  name: string;
  status: TraceStatus;
  start_time: string;
  end_time: string | null;
  duration_ms: number | null;
  environment: string | null;
  release: string | null;
  user_id: string | null;
  session_id: string | null;
  models: string[];
  providers: string[];
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  cost_usd: number | null;
  cost_status: string | null;
  span_count: number;
  error_span_count: number;
  error_type: string | null;
  error_message: string | null;
  tags: string[];
  source: string;
};

export type TraceList = { items: TraceSummary[]; next_cursor: string | null; total: number; total_capped: boolean };

export type SpanSkeleton = {
  id: string;
  span_id: string;
  parent_span_id: string | null;
  name: string;
  kind: SpanKind;
  status: "ok" | "error" | "unset";
  start_time: string;
  end_time: string | null;
  duration_ms: number | null;
  provider: string | null;
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cached_tokens: number | null;
  total_tokens: number | null;
  usage_source: string | null;
  cost_usd: number | null;
  cost_status: string | null;
  error_type: string | null;
  error_message: string | null;
  retry_count: number | null;
};

export type SpanDetail = SpanSkeleton & {
  trace_id: string;
  input: unknown;
  output: unknown;
  attributes: Record<string, unknown>;
  error_stacktrace: string | null;
  pricing_version: string | null;
};

export type TraceDetail = {
  trace: TraceSummary & { root_span_id: string | null; input: unknown; output: unknown; metadata: Record<string, unknown> };
  spans: SpanSkeleton[];
  spans_truncated: boolean;
};

export type Finding = {
  rule: string;
  severity: "critical" | "high" | "medium" | "low" | "info";
  title: string;
  detail: string;
  span_ids: string[];
  evidence: Record<string, unknown>;
};

export type Investigation = {
  id: string;
  kind: "deterministic" | "llm";
  status: "queued" | "running" | "completed" | "failed";
  summary: string | null;
  findings: Record<string, unknown> | null;
  provider: string | null;
  model: string | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
};

export type Overview = {
  range: { start: string; end: string; bucket: string };
  totals: {
    traces: number;
    ok: number;
    error: number;
    incomplete: number;
    error_rate: number | null;
    p50_ms: number | null;
    p95_ms: number | null;
    p99_ms: number | null;
    input_tokens: number | null;
    output_tokens: number | null;
    total_tokens: number | null;
    cost_usd: number | null;
    unpriced_traces: number;
  };
  series: {
    bucket: string;
    traces: number;
    errors: number;
    error_rate: number | null;
    p95_ms: number | null;
    cost_usd: number | null;
    total_tokens: number | null;
  }[];
  models: {
    provider: string | null;
    model: string;
    calls: number;
    errors: number;
    total_tokens: number | null;
    cost_usd: number | null;
    unpriced_calls: number;
    p50_ms: number | null;
  }[];
  top_errors: {
    error_type: string;
    message: string;
    kind: SpanKind;
    occurrences: number;
    last_seen: string;
    example_trace_id: string;
  }[];
  latency_histogram: { lower_ms: number; upper_ms: number; count: number }[];
  recent_failed: {
    trace_id: string;
    name: string;
    start_time: string;
    duration_ms: number | null;
    error_type: string | null;
    error_message: string | null;
  }[];
  slowest: { trace_id: string; name: string; start_time: string; duration_ms: number; status: TraceStatus }[];
};

export type Onboarding = {
  organization_id: string | null;
  project_id: string | null;
  integration: string | null;
  completed_steps: string[];
  first_trace_received: boolean;
  steps: string[];
};

export type EvaluatorSpec = { type: string; config?: Record<string, unknown> };

export type Dataset = {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  example_count?: number;
  run_count?: number;
};

export type Example = {
  id: string;
  input: unknown;
  expected_output: unknown;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type RunSummary = {
  total: number;
  passed: number;
  failed: number;
  errored: number;
  ungraded: number;
  pass_rate: number | null;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
  total_cost_usd: number | null;
  cost_complete: boolean;
  input_tokens: number | null;
  output_tokens: number | null;
  has_probabilistic: boolean;
};

export type EvalRun = {
  id: string;
  dataset_id: string;
  name: string;
  target_type: "model" | "sdk";
  target_config: Record<string, unknown>;
  evaluators: EvaluatorSpec[];
  makes_external_calls: boolean;
  status: "queued" | "running" | "completed" | "failed";
  summary: Partial<RunSummary> | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
};

export type Score = {
  evaluator: string;
  probabilistic: boolean;
  passed: boolean | null;
  score: number | null;
  detail: string;
  judge_model?: string;
};

export type EvalResult = {
  example_id: string;
  input: unknown;
  expected_output: unknown;
  output: unknown;
  passed: boolean | null;
  scores: Score[];
  latency_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  error: string | null;
  trace_id: string | null;
};

export type Comparison = {
  base: { id: string; name: string; summary: Partial<RunSummary> };
  candidate: { id: string; name: string; summary: Partial<RunSummary> };
  deltas: Record<"pass_rate" | "avg_latency_ms" | "p95_latency_ms" | "total_cost_usd", number | null>;
  counts: Record<"regressed" | "fixed" | "unchanged_pass" | "unchanged_fail" | "other", number>;
  rows: {
    example_id: string;
    input: unknown;
    expected_output: unknown;
    base: { passed: boolean | null; output: unknown; latency_ms: number | null; error: string | null };
    candidate: { passed: boolean | null; output: unknown; latency_ms: number | null; error: string | null };
    change: "regressed" | "fixed" | "unchanged_pass" | "unchanged_fail" | "other";
  }[];
};

export type PromptVersion = {
  id: string;
  version: number;
  content: string;
  variables: string[];
  notes: string | null;
  tags: string[];
  status: "draft" | "published";
  created_at: string;
  published_at: string | null;
  created_by: string | null;
};

export type PromptSummary = {
  id: string;
  name: string;
  description: string | null;
  latest_version: number | null;
  active_version: number | null;
  updated_at: string;
};

export type PromptDetail = Omit<PromptSummary, "latest_version"> & { created_at: string; versions: PromptVersion[] };

export type IntegrationItem = {
  id: string;
  name: string;
  status: "implemented" | "not_implemented";
  tested: boolean;
  install: string | null;
  docs: string;
  notes?: string;
  receiving_data: boolean;
  data: { count: number; unit: string; last_seen: string } | null;
};

export type ProviderCredentials = {
  encryption_available: boolean;
  items: { provider: "openai" | "anthropic"; secret_last4: string; default_model: string; updated_at: string }[];
  server_fallback: { provider: string | null; model: string | null; configured: boolean };
};

export type AuditEvent = {
  id: string;
  action: string;
  actor_user_id: string | null;
  target_type: string;
  target_id: string | null;
  project_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
};
