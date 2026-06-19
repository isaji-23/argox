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
  }): Promise<TraceListResponse> {
    const searchParams = new URLSearchParams();
    if (params.skip !== undefined) searchParams.set('skip', params.skip.toString());
    if (params.limit !== undefined) searchParams.set('limit', params.limit.toString());
    if (params.trace_id) searchParams.set('trace_id', params.trace_id);
    if (params.agent_name && params.agent_name !== 'all') searchParams.set('agent_name', params.agent_name);
    if (params.status && params.status !== 'all') searchParams.set('status', params.status);
    if (params.decision && params.decision !== 'all') searchParams.set('decision', params.decision);
    if (params.sort) searchParams.set('sort', params.sort);

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
  }
};
