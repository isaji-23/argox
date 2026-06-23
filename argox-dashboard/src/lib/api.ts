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

    const res = await fetch(`${API_BASE}/traces?${searchParams.toString()}`);
    if (!res.ok) throw new APIError('Failed to fetch traces', res.status);
    return res.json();
  },

  async getTrace(traceId: string): Promise<TraceDetailResponse> {
    const res = await fetch(`${API_BASE}/traces/${encodeURIComponent(traceId)}`);
    if (!res.ok) {
      const msg = res.status === 404 ? `Trace ${traceId} not found` : `Failed to fetch trace ${traceId}`;
      throw new APIError(msg, res.status);
    }
    return res.json();
  },

  async getCostMetrics(windowHours: number = 24): Promise<CostMetricsResponse> {
    const res = await fetch(`${API_BASE}/metrics/cost?window_hours=${windowHours}`);
    if (!res.ok) throw new APIError('Failed to fetch cost metrics', res.status);
    return res.json();
  },

  async getLatencyMetrics(windowHours: number = 24): Promise<LatencyMetricsResponse> {
    const res = await fetch(`${API_BASE}/metrics/latency?window_hours=${windowHours}`);
    if (!res.ok) throw new APIError('Failed to fetch latency metrics', res.status);
    return res.json();
  },

  async getSuccessMetrics(windowHours: number = 24): Promise<SuccessMetricsResponse> {
    const res = await fetch(`${API_BASE}/metrics/success?window_hours=${windowHours}`);
    if (!res.ok) throw new APIError('Failed to fetch success metrics', res.status);
    return res.json();
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

  async getPolicyYaml(id: string): Promise<string> {
    const res = await fetch(`${API_BASE}/policies/${encodeURIComponent(id)}`, {
      headers: { 'Accept': 'application/x-yaml' }
    });
    if (!res.ok) throw new APIError(`Failed to fetch policy ${id} YAML`, res.status);
    return res.text();
  },

  async getPolicyVersionYaml(id: string, version: number): Promise<string> {
    const res = await fetch(`${API_BASE}/policies/${encodeURIComponent(id)}/v${version}`, {
      headers: { 'Accept': 'application/x-yaml' }
    });
    if (!res.ok) throw new APIError(`Failed to fetch policy ${id} v${version} YAML`, res.status);
    return res.text();
  },

  async createPolicy(policy: { id: string; status: string; rules: any[]; created_by?: string }): Promise<PolicyResponse> {
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

  async updatePolicy(id: string, policy: { status: string; rules: any[]; created_by?: string }): Promise<PolicyResponse> {
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

export interface PolicySummary {
  id: string;
  status: 'active' | 'draft' | 'archived';
  latest_version: number;
  active_version: number | null;
}

export interface PolicyListResponse {
  policies: PolicySummary[];
  total: number;
}

export interface PolicyRule {
  id: string;
  trigger: string;
  condition: {
    metric: string;
    operator: 'eq' | 'neq' | 'gt' | 'gte' | 'lt' | 'lte' | 'contains' | 'in';
    threshold: any;
  };
  action: 'block' | 'alert' | 'ok';
  enforcement?: string;
}

export interface PolicyResponse {
  id: string;
  version: number;
  status: 'active' | 'draft' | 'archived';
  rules: PolicyRule[];
  created_by?: string | null;
  updated_at?: string | null;
  content_hash: string;
}

export interface PolicyValidateResponse {
  valid: boolean;
  errors: string[];
  policy?: any;
}

