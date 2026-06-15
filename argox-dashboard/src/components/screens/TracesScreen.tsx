import { useState, useEffect } from 'react';
import { cn } from '../../lib/utils';
import { Icon } from '../shared/Icon';
import { Button } from '../ui/Button';
import { StatusDot } from '../ui/Badge';
import { DecisionBadge } from '../shared/DecisionBadge';
import { Panel } from '../ui/Panel';
import { ErrorState } from '../ui/States';
import { SearchInput } from '../ui/SearchInput';
import { Select } from '../ui/Select';
import { DataTable } from '../ui/DataTable';
import type { Column } from '../ui/DataTable';
import { api, type TraceSummary } from '../../lib/api';
import { AGENTS, TIME_RANGES } from '../../data/mockData';

interface TracesScreenProps {
  timeRange: string;
  agent: string;
  onOpenTrace: (trace: { id: string }) => void;
}

export function TracesScreen({ timeRange, agent, onOpenTrace }: TracesScreenProps) {
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<{ key: string; dir: 'asc' | 'desc' }>({ key: 'start_time', dir: 'desc' });
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [filterStatus, setFilterStatus] = useState('all');
  const [filterDecision, setFilterDecision] = useState('all');
  const [filterAgent, setFilterAgent] = useState(agent);
  const [error, setError] = useState<string | null>(null);
  const pageSize = 10;

  useEffect(() => {
    setFilterAgent(agent);
  }, [agent]);

  // Debounce search query
  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedQuery(query);
    }, 300);
    return () => clearTimeout(handler);
  }, [query]);

  const fetchTraces = async () => {
    setLoading(true);
    setError(null);

    // Map frontend sort keys to backend fields
    const sortMap: Record<string, string> = {
      start_time: 'start_time',
      total_duration_ms: 'duration',
      total_cost: 'cost',
      span_count: 'spans'
    };
    const backendSort = sortMap[sort.key] ? `${sortMap[sort.key]}:${sort.dir}` : undefined;

    try {
      const data = await api.listTraces({
        skip: (page - 1) * pageSize,
        limit: pageSize,
        trace_id: debouncedQuery || undefined,
        agent_name: filterAgent,
        status: filterStatus,
        decision: filterDecision,
        sort: backendSort,
      });
      setTraces(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTraces();
  }, [page, debouncedQuery, filterStatus, filterDecision, filterAgent, sort]);

  useEffect(() => {
    setPage(1);
  }, [debouncedQuery, filterStatus, filterDecision, filterAgent, sort]);

  const fmtMs = (ms: number) => ms >= 1000 ? (ms / 1000).toFixed(2) + 's' : Math.round(ms) + 'ms';
  const fmtDate = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  const columns: Column<TraceSummary>[] = [
    {
      key: 'trace_id',
      label: 'Trace',
      width: '1.5fr',
      sortable: false,
      render: (r) => (
        <div className="flex items-center gap-2.5 min-w-0">
          <StatusDot status={r.status || 'ok'} />
          <div className="min-w-0">
            <div className={cn(
              "font-mono text-sm font-semibold truncate",
              r.decision === 'block' ? "text-block-bright" : "text-text-primary"
            )}>
              {(r.trace_id || '').slice(0, 8)}...
            </div>
            <div className="font-mono text-2xs text-text-faint truncate uppercase">
              {r.trace_id}
            </div>
          </div>
        </div>
      )
    },
    {
      key: 'agent_name',
      label: 'Agent',
      width: '1fr',
      sortable: false,
      render: (r) => (
        <span className="inline-flex items-center gap-1.5 text-sm text-text-secondary font-mono">
          <Icon name="bolt" size={12} className="text-text-faint" />
          {r.agent_name || 'unknown'}
        </span>
      )
    },
    {
      key: 'start_time',
      label: 'Started',
      width: '0.9fr',
      sortable: true,
      render: (r) => (
        <span className="text-xs text-text-muted font-mono">{r.start_time ? fmtDate(r.start_time) : '-'}</span>
      )
    },
    {
      key: 'total_duration_ms',
      label: 'Duration',
      width: '0.8fr',
      align: 'right',
      sortable: true,
      render: (r) => (
        <span className="text-sm font-mono text-text-secondary tabular-nums">
          {fmtMs(r.total_duration_ms || 0)}
        </span>
      )
    },
    {
      key: 'span_count',
      label: 'Spans',
      width: '0.55fr',
      align: 'right',
      sortable: true,
      render: (r) => (
        <span className="text-sm font-mono text-text-muted tabular-nums">
          {r.span_count}
        </span>
      )
    },
    {
      key: 'total_cost',
      label: 'Cost',
      width: '0.7fr',
      align: 'right',
      sortable: true,
      render: (r) => (
        <span className="text-sm font-mono text-text-secondary tabular-nums">
          ${r.total_cost?.toFixed(4) || '0.0000'}
        </span>
      )
    },
    {
      key: 'decision',
      label: 'Policy',
      width: '0.85fr',
      align: 'right',
      sortable: false,
      render: (r) => <DecisionBadge decision={r.decision || 'allow'} size="sm" />
    },
  ];

  return (
    <div className="ax-fade-in p-6 pt-5 pb-10 max-w-[1320px] mx-auto">
      <div className="flex items-end justify-between mb-4">
        <div>
          <h1 className="m-0 text-xl font-semibold tracking-tight">Traces</h1>
          <p className="m-0 mt-0.5 text-sm text-text-muted">
            {total.toLocaleString()} traces · {TIME_RANGES.find((t) => t.value === timeRange)?.label.toLowerCase()}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" icon="refresh" onClick={fetchTraces} className={loading ? "opacity-50 pointer-events-none" : ""}>
            {loading ? 'Refreshing...' : 'Refresh'}
          </Button>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-2.5 mb-3.5 flex-wrap">
        <SearchInput
          value={query}
          onChange={setQuery}
          placeholder="Search trace_id…"
          width={280}
        />
        <div className="w-px h-[22px] bg-border mx-1" />
        
        <div className="flex items-center bg-surface-3 border border-border-strong rounded-md overflow-hidden">
          <span className="text-xs text-text-muted pl-2.5 pr-0.5 whitespace-nowrap">Agent</span>
          <Select
            value={filterAgent}
            onChange={setFilterAgent}
            options={[{ value: 'all', label: 'All' }, ...AGENTS.map((a) => ({ value: a, label: a }))]}
            minWidth={100}
            size="sm"
            className="border-none rounded-none"
          />
        </div>

        <div className="flex items-center bg-surface-3 border border-border-strong rounded-md overflow-hidden">
          <span className="text-xs text-text-muted pl-2.5 pr-0.5 whitespace-nowrap">Status</span>
          <Select
            value={filterStatus}
            onChange={setFilterStatus}
            options={[{ value: 'all', label: 'All' }, { value: 'ok', label: 'OK' }, { value: 'error', label: 'Error' }]}
            minWidth={80}
            size="sm"
            className="border-none rounded-none"
          />
        </div>

        <div className="flex items-center bg-surface-3 border border-border-strong rounded-md overflow-hidden">
          <span className="text-xs text-text-muted pl-2.5 pr-0.5 whitespace-nowrap">Decision</span>
          <Select
            value={filterDecision}
            onChange={setFilterDecision}
            options={[{ value: 'all', label: 'All' }, { value: 'allow', label: 'Allow' }, { value: 'warn', label: 'Warn' }, { value: 'block', label: 'Block' }]}
            minWidth={90}
            size="sm"
            className="border-none rounded-none"
          />
        </div>

        {(filterStatus !== 'all' || filterDecision !== 'all' || filterAgent !== 'all' || query) && (
          <Button
            variant="ghost"
            size="sm"
            icon="x"
            onClick={() => {
              setQuery('');
              setFilterStatus('all');
              setFilterDecision('all');
              setFilterAgent('all');
            }}
          >
            Clear
          </Button>
        )}
      </div>

      {error ? (
        <Panel className="border-block-border">
          <ErrorState
            title="Failed to query traces"
            body={error}
            onRetry={fetchTraces}
          />
        </Panel>
      ) : (
        <DataTable
          columns={columns}
          rows={traces}
          loading={loading}
          page={page}
          pageSize={pageSize}
          total={total}
          onPage={setPage}
          sort={sort}
          onSort={(key) => setSort((s) => ({ key, dir: s.key === key && s.dir === 'desc' ? 'asc' : 'desc' }))}
          onRowClick={(r) => onOpenTrace({ id: r.trace_id })}
          rowKey={(r) => r.trace_id}
          rowAccent={(r) => r.decision === 'block'}
        />
      )}
    </div>
  );
}
