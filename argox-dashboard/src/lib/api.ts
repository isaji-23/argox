import type { components } from '../api/schema';
import { getToken, signalAuthRequired } from './auth';

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
  attributes: Record<string, any>;
}

export interface TraceDetailResponse {
  trace_id: string;
  spans: SpanDetail[];
  truncated: boolean;
  duration_ms: number | null;
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

export const api = {
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
    const res = await fetch(`${API_BASE}/policies`);
    if (!res.ok) throw new APIError('Failed to fetch policies', res.status);
    return res.json();
  },

  async getPolicy(id: string): Promise<PolicyResponse> {
    const res = await fetch(`${API_BASE}/policies/${encodeURIComponent(id)}`);
    if (!res.ok) throw new APIError(`Failed to fetch policy ${id}`, res.status);
    return res.json();
  },

  async getPolicyVersion(id: string, version: number): Promise<PolicyResponse> {
    const res = await fetch(`${API_BASE}/policies/${encodeURIComponent(id)}/v${version}`);
    if (!res.ok) throw new APIError(`Failed to fetch policy ${id} v${version}`, res.status);
    return res.json();
  },

  async getPolicyVersionYaml(id: string, version: number): Promise<string> {
    const res = await fetch(`${API_BASE}/policies/${encodeURIComponent(id)}/v${version}`, {
      headers: { 'Accept': 'application/x-yaml' }
    });
    if (!res.ok) throw new APIError(`Failed to fetch policy ${id} v${version} YAML`, res.status);
    return res.text();
  },

  async createPolicy(policy: { id: string; status: 'active' | 'draft' | 'archived'; rules: PolicyRule[]; created_by?: string }): Promise<PolicyResponse> {
    const res = await fetch(`${API_BASE}/policies`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(policy)
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      throw new APIError(errBody.detail || 'Failed to create policy', res.status);
    }
    return res.json();
  },

  async updatePolicy(id: string, policy: { status: 'active' | 'draft' | 'archived'; rules: PolicyRule[]; created_by?: string }): Promise<PolicyResponse> {
    const res = await fetch(`${API_BASE}/policies/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(policy)
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      throw new APIError(errBody.detail || 'Failed to update policy', res.status);
    }
    return res.json();
  },

  async validatePolicy(yamlContent: string): Promise<PolicyValidateResponse> {
    const res = await fetch(`${API_BASE}/policies/validate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ yaml: yamlContent })
    });
    if (!res.ok) throw new APIError('Failed to validate policy', res.status);
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
  percentiles: LatencyPercentiles;
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

