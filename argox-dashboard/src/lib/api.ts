import type { components } from '../api/schema';
import { getToken, getAdminToken, signalAuthRequired } from './auth';

const API_BASE = '/api/v1';

export interface TraceSummary {
  trace_id: string;
  start_time: string;
  end_time: string;
  total_duration_ms: number;
  total_cost: number;
  agent_name: string;
  agent_version: string;
  span_count: number;
  status: 'ok' | 'error';
  decision: 'allow' | 'block' | 'warn';
}

export interface TraceListResponse {
  items: TraceSummary[];
  total: number;
  skip: number;
  limit: number;
}

export interface SpanDetail {
  span_id: string;
  parent_span_id: string | null;
  name: string;
  start_time: string;
  end_time: string;
  duration_ms: number;
  agent_name: string | null;
  agent_version: string | null;
  policy_decision: string | null;
  run_cost: number | null;
  run_success: boolean | null;
  attributes: Record<string, unknown>;
}

export interface TraceDetailResponse {
  trace_id: string;
  spans: SpanDetail[];
  truncated: boolean;
  duration_ms: number | null;
}

export interface RunToolCall {
  name: string;
  duration?: number | null;
  blocked: boolean;
  result?: string | null;
  block_reason?: string | null;
}

export interface RunToolBlocked {
  name: string;
  reason?: string | null;
}

export interface RunApiCallToken {
  call: number;
  input?: number | null;
  output?: number | null;
  total?: number | null;
}

export interface RunDetail {
  run_id: string;
  trace_id?: string | null;
  agent_name?: string | null;
  agent_version?: string | null;
  timestamp?: string | null;
  success?: boolean | null;
  duration_seconds?: number | null;
  cost_usd?: number | null;
  model?: string | null;
  prompt?: string;
  final_output?: string;
  tokens?: {
    input?: number;
    output?: number;
    total?: number;
    by_api_call?: RunApiCallToken[];
  };
  tools?: {
    available?: string[];
    blocked?: RunToolBlocked[];
    called?: RunToolCall[];
  };
  policies?: {
    input_passed?: boolean;
    output_passed?: boolean;
    violations?: string[];
  };
  exporter_errors?: string[];
  phase_timings_ms?: Record<string, number>;
}

export class APIError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'APIError';
    this.status = status;
  }
}

/**
 * Single fetch wrapper for the Collector API.
 *
 * Attaches `Authorization: Bearer <token>` whenever an API key is stored; when
 * none is set (e.g. auth disabled), the request goes out unauthenticated and
 * behaves as before. On `401`/`403` it signals the UI to prompt for a key and
 * raises an `APIError` carrying the status so callers can react.
 *
 * Args:
 *   path: API path relative to `API_BASE`.
 *   errorMessage: fallback message for non-auth failures.
 *
 * Returns:
 *   The parsed JSON response body.
 */
async function apiFetch<T>(path: string, errorMessage: string): Promise<T> {
  const token = getToken();
  const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};

  const res = await fetch(`${API_BASE}${path}`, { headers });
  if (!res.ok) {
    if (res.status === 401 || res.status === 403) {
      signalAuthRequired();
      const msg = res.status === 401
        ? 'Authentication required: enter a Collector API key.'
        : 'Access denied: this key lacks the read scope.';
      throw new APIError(msg, res.status);
    }
    throw new APIError(errorMessage, res.status);
  }
  return res.json();
}

/**
 * Fetch wrapper for the admin-only key-management endpoints (DASH-06).
 *
 * Unlike {@link apiFetch} this attaches the separately stored **admin** key and
 * does NOT call `signalAuthRequired` on `401`/`403` — that event opens the read
 * key dialog, which is the wrong prompt here. The key-management screen handles
 * auth failures inline via the `APIError` status instead. Supports request
 * bodies and returns `null` for empty (`204`) responses.
 *
 * Args:
 *   path: API path relative to `API_BASE`.
 *   errorMessage: fallback message for non-auth failures.
 *   init: optional fetch overrides (method, JSON body).
 *
 * Returns:
 *   The parsed JSON response body, or `null` on a `204 No Content`.
 */
async function adminFetch<T>(
  path: string,
  errorMessage: string,
  init: { method?: string; body?: unknown } = {},
): Promise<T> {
  const token = getAdminToken();
  const headers: Record<string, string> = token
    ? { Authorization: `Bearer ${token}` }
    : {};
  if (init.body !== undefined) headers['Content-Type'] = 'application/json';

  const res = await fetch(`${API_BASE}${path}`, {
    method: init.method ?? 'GET',
    headers,
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
  });

  if (!res.ok) {
    if (res.status === 401 || res.status === 403) {
      const msg = res.status === 401
        ? 'Admin authentication required: enter an admin-scoped Collector key.'
        : 'Access denied: this key lacks the admin scope.';
      throw new APIError(msg, res.status);
    }
    const errBody = await res.json().catch(() => ({} as { detail?: string }));
    throw new APIError(errBody.detail || errorMessage, res.status);
  }
  if (res.status === 204) return null as T;
  return res.json();
}

/**
 * Fetch wrapper for the policy endpoints (DASH-07).
 *
 * Mirrors {@link apiFetch}'s auth handling — it attaches the stored read key,
 * which also carries the `policy-read`/`policy-write` scopes — but additionally
 * supports request bodies, a custom `Accept` (the YAML view), and returns the
 * raw `Response` so callers can read `.json()` or `.text()`. Policy calls used
 * bare `fetch` with no `Authorization` header, so every one of them returned
 * `401` whenever Collector auth was enabled (it only worked with auth disabled).
 *
 * Args:
 *   path: API path relative to `API_BASE`.
 *   errorMessage: fallback message for non-auth failures.
 *   init: optional fetch overrides (method, JSON body, Accept header).
 */
async function policyFetch(
  path: string,
  errorMessage: string,
  init: { method?: string; body?: unknown; accept?: string } = {},
): Promise<Response> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (init.accept) headers['Accept'] = init.accept;
  if (init.body !== undefined) headers['Content-Type'] = 'application/json';

  const res = await fetch(`${API_BASE}${path}`, {
    method: init.method ?? 'GET',
    headers,
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
  });

  if (!res.ok) {
    if (res.status === 401 || res.status === 403) {
      signalAuthRequired();
      const msg = res.status === 401
        ? 'Authentication required: enter a Collector API key.'
        : 'Access denied: this key lacks the policy scope.';
      throw new APIError(msg, res.status);
    }
    const errBody = await res.json().catch(() => ({} as { detail?: string }));
    throw new APIError(errBody.detail || errorMessage, res.status);
  }
  return res;
}

export const api = {
  async listKeys(): Promise<ApiKeyListResponse> {
    return adminFetch<ApiKeyListResponse>('/keys', 'Failed to list API keys');
  },

  async createKey(payload: ApiKeyCreateRequest): Promise<ApiKeyCreateResponse> {
    return adminFetch<ApiKeyCreateResponse>('/keys', 'Failed to create API key', {
      method: 'POST',
      body: payload,
    });
  },

  async revokeKey(keyId: string): Promise<void> {
    await adminFetch<null>(
      `/keys/${encodeURIComponent(keyId)}`,
      `Failed to revoke key ${keyId}`,
      { method: 'DELETE' },
    );
  },

  async listTraces(params: {
    skip?: number;
    limit?: number;
    trace_id?: string;
    agent_name?: string;
    status?: string;
    decision?: string;
    sort?: string;
    window_hours?: number;
  }): Promise<TraceListResponse> {
    const searchParams = new URLSearchParams();
    if (params.skip !== undefined) searchParams.set('skip', params.skip.toString());
    if (params.limit !== undefined) searchParams.set('limit', params.limit.toString());
    if (params.trace_id) searchParams.set('trace_id', params.trace_id);
    if (params.agent_name && params.agent_name !== 'all') searchParams.set('agent_name', params.agent_name);
    if (params.status && params.status !== 'all') searchParams.set('status', params.status);
    if (params.decision && params.decision !== 'all') searchParams.set('decision', params.decision);
    if (params.sort) searchParams.set('sort', params.sort);
    if (params.window_hours !== undefined) searchParams.set('window_hours', params.window_hours.toString());

    return apiFetch<TraceListResponse>(`/traces?${searchParams.toString()}`, 'Failed to fetch traces');
  },

  async getTrace(traceId: string): Promise<TraceDetailResponse> {
    try {
      return await apiFetch<TraceDetailResponse>(
        `/traces/${encodeURIComponent(traceId)}`,
        `Failed to fetch trace ${traceId}`,
      );
    } catch (err) {
      if (err instanceof APIError && err.status === 404) {
        throw new APIError(`Trace ${traceId} not found`, 404);
      }
      throw err;
    }
  },

  async getRunByTrace(traceId: string): Promise<RunDetail> {
    return apiFetch<RunDetail>(
      `/runs/by-trace/${encodeURIComponent(traceId)}`,
      `Failed to load run record for trace ${traceId}`,
    );
  },

  async getCostMetrics(windowHours: number = 24): Promise<CostMetricsResponse> {
    return apiFetch<CostMetricsResponse>(`/metrics/cost?window_hours=${windowHours}`, 'Failed to fetch cost metrics');
  },

  async getLatencyMetrics(windowHours: number = 24): Promise<LatencyMetricsResponse> {
    return apiFetch<LatencyMetricsResponse>(`/metrics/latency?window_hours=${windowHours}`, 'Failed to fetch latency metrics');
  },

  async getSuccessMetrics(windowHours: number = 24): Promise<SuccessMetricsResponse> {
    return apiFetch<SuccessMetricsResponse>(`/metrics/success?window_hours=${windowHours}`, 'Failed to fetch success metrics');
  },

  async listPolicies(): Promise<PolicyListResponse> {
    const res = await policyFetch('/policies', 'Failed to fetch policies');
    return res.json();
  },

  async getPolicy(id: string): Promise<PolicyResponse> {
    const res = await policyFetch(
      `/policies/${encodeURIComponent(id)}`,
      `Failed to fetch policy ${id}`,
    );
    return res.json();
  },

  async getPolicyVersion(id: string, version: number): Promise<PolicyResponse> {
    const res = await policyFetch(
      `/policies/${encodeURIComponent(id)}/v${version}`,
      `Failed to fetch policy ${id} v${version}`,
    );
    return res.json();
  },

  async getPolicyVersionYaml(id: string, version: number): Promise<string> {
    const res = await policyFetch(
      `/policies/${encodeURIComponent(id)}/v${version}`,
      `Failed to fetch policy ${id} v${version} YAML`,
      { accept: 'application/x-yaml' },
    );
    return res.text();
  },

  async createPolicy(policy: { id: string; status: 'active' | 'draft' | 'archived'; rules: PolicyRule[]; created_by?: string }): Promise<PolicyResponse> {
    const res = await policyFetch('/policies', 'Failed to create policy', {
      method: 'POST',
      body: policy,
    });
    return res.json();
  },

  async updatePolicy(id: string, policy: { status: 'active' | 'draft' | 'archived'; rules: PolicyRule[]; created_by?: string }): Promise<PolicyResponse> {
    const res = await policyFetch(
      `/policies/${encodeURIComponent(id)}`,
      'Failed to update policy',
      { method: 'PUT', body: policy },
    );
    return res.json();
  },

  async validatePolicy(yamlContent: string): Promise<PolicyValidateResponse> {
    const res = await policyFetch('/policies/validate', 'Failed to validate policy', {
      method: 'POST',
      body: { yaml: yamlContent },
    });
    return res.json();
  }
};

export interface CostTimeSeriesPoint {
  bucket: string;
  model: string;
  cost: number;
}

export interface AgentSpendPoint {
  agent_name: string;
  spend: number;
}

export interface CostMetricsResponse {
  window_hours: number;
  total_cost: number;
  trace_count: number;
  timeline: CostTimeSeriesPoint[];
  top_agents: AgentSpendPoint[];
}

export interface LatencyHistogramBin {
  bin_min: number;
  bin_max: number;
  count: number;
}

export interface LatencyPercentiles {
  p50: number;
  p95: number;
  p99: number;
}

export interface LatencyMetricsResponse {
  window_hours: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  trace_count: number;
  percentiles?: LatencyPercentiles;
  histogram: LatencyHistogramBin[];
}

export interface SuccessTimeSeriesPoint {
  bucket: string;
  total_runs: number;
  successful_runs: number;
  success_rate: number | null;
}

export interface BlockedToolPoint {
  tool_name: string;
  blocked_count: number;
}

export interface SuccessMetricsResponse {
  window_hours: number;
  total_runs: number;
  successful_runs: number;
  success_rate: number | null;
  timeline: SuccessTimeSeriesPoint[];
  top_blocked_tools: BlockedToolPoint[];
}

export type PolicySummary = components["schemas"]["PolicySummary"];

export interface PolicyListResponse {
  policies: PolicySummary[];
  total: number;
}

export type PolicyRule = components["schemas"]["PolicyRule"];
export type PolicyResponse = components["schemas"]["PolicyResponse"];

export interface PolicyValidateResponse {
  valid: boolean;
  errors: string[];
  policy?: Omit<PolicyResponse, 'content_hash'> | null;
}

// API key management (DASH-06). Mirrors the Collector's admin-only key CRUD
// (`/api/v1/keys`); see argox-collector routers/keys.py.

/** The scopes a key may grant. `admin` implies all others. */
export type KeyScope = 'read' | 'ingest' | 'policy-read' | 'policy-write' | 'admin';

export interface ApiKeyCreateRequest {
  name: string;
  scopes: KeyScope[];
  /** Optional lifetime in seconds; omit for a non-expiring key. */
  expires_in?: number;
}

/** Non-secret metadata view of a stored key. */
export interface ApiKeyView {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  created_at: string;
  created_by?: string | null;
  revoked_at?: string | null;
  revoked: boolean;
  expires_at?: string | null;
}

/** Create response: the metadata view plus the one-time raw secret. */
export interface ApiKeyCreateResponse extends ApiKeyView {
  key: string;
}

export interface ApiKeyListResponse {
  keys: ApiKeyView[];
  total: number;
}

