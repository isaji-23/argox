import { useState, useEffect, useMemo } from 'react';
import { cn } from '../../lib/utils';
import { Icon } from '../shared/Icon';
import { Button } from '../ui/Button';
import { Badge, StatusDot } from '../ui/Badge';
import { DecisionBadge } from '../shared/DecisionBadge';
import { Panel } from '../ui/Panel';
import { ErrorState } from '../ui/States';
import { SearchInput } from '../ui/SearchInput';
import { Select } from '../ui/Select';
import { DataTable } from '../ui/DataTable';
import type { Column } from '../ui/DataTable';
import { buildTraces, AGENTS, TIME_RANGES } from '../../data/mockData';

interface Trace {
  id: string;
  name: string;
  agent: string;
  env: string;
  model: string;
  startedHuman: string;
  durationMs: number;
  status: string;
  decision: any;
  spanCount: number;
}

interface TracesScreenProps {
  timeRange: string;
  agent: string;
  onOpenTrace: (trace: any) => void;
}

export function TracesScreen({ timeRange, agent, onOpenTrace }: TracesScreenProps) {
  const allTraces = useMemo(() => buildTraces(), []);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<{ key: string; dir: 'asc' | 'desc' }>({ key: 'startedHuman', dir: 'desc' });
  const [query, setQuery] = useState('');
  const [filterStatus, setFilterStatus] = useState('all');
  const [filterDecision, setFilterDecision] = useState('all');
  const [filterAgent, setFilterAgent] = useState(agent);
  const [errorMode, setErrorMode] = useState(false);
  const pageSize = 9;

  useEffect(() => {
    setFilterAgent(agent);
  }, [agent]);

  useEffect(() => {
    setLoading(true);
    const timeout = setTimeout(() => setLoading(false), 480);
    return () => clearTimeout(timeout);
  }, [page, sort, query, filterStatus, filterDecision, filterAgent, errorMode]);

  const filteredTraces = useMemo(() => {
    let results = allTraces.filter((t) =>
      (filterStatus === 'all' || t.status === filterStatus) &&
      (filterDecision === 'all' || t.decision === filterDecision) &&
      (filterAgent === 'all' || t.agent === filterAgent) &&
      (query === '' || t.name.toLowerCase().includes(query.toLowerCase()) || t.id.includes(query) || t.agent.includes(query)));

    const dir = sort.dir === 'asc' ? 1 : -1;
    results = [...results].sort((a: any, b: any) => {
      const av = a[sort.key];
      const bv = b[sort.key];
      if (typeof av === 'string') return av.localeCompare(bv) * dir;
      return (av - bv) * dir;
    });
    return results;
  }, [allTraces, filterStatus, filterDecision, filterAgent, query, sort]);

  useEffect(() => {
    setPage(1);
  }, [query, filterStatus, filterDecision, filterAgent]);

  const pageRows = filteredTraces.slice((page - 1) * pageSize, page * pageSize);
  const blockedTotal = allTraces.filter((t) => t.decision === 'block').length;

  const fmtMs = (ms: number) => ms >= 1000 ? (ms / 1000).toFixed(2) + 's' : ms + 'ms';

  const columns: Column<Trace>[] = [
    {
      key: 'name',
      label: 'Trace',
      width: '1.5fr',
      sortable: true,
      render: (r) => (
        <div className="flex items-center gap-2.5 min-w-0">
          <StatusDot status={r.status} />
          <div className="min-w-0">
            <div className={cn(
              "font-mono text-sm font-semibold truncate",
              r.decision === 'block' ? "text-block-bright" : "text-text-primary"
            )}>
              {r.name}
            </div>
            <div className="font-mono text-2xs text-text-faint truncate uppercase">
              {r.id.slice(0, 12)}
            </div>
          </div>
        </div>
      )
    },
    {
      key: 'agent',
      label: 'Agent',
      width: '1fr',
      sortable: true,
      render: (r) => (
        <span className="inline-flex items-center gap-1.5 text-sm text-text-secondary font-mono">
          <Icon name="bolt" size={12} className="text-text-faint" />
          {r.agent}
        </span>
      )
    },
    {
      key: 'env',
      label: 'Env',
      width: '0.7fr',
      render: (r) => <Badge tone="neutral" mono>{r.env}</Badge>
    },
    {
      key: 'startedHuman',
      label: 'Started',
      width: '0.9fr',
      sortable: true,
      render: (r) => (
        <span className="text-xs text-text-muted font-mono">{r.startedHuman}</span>
      )
    },
    {
      key: 'durationMs',
      label: 'Duration',
      width: '0.8fr',
      align: 'right',
      sortable: true,
      render: (r) => (
        <span className="text-sm font-mono text-text-secondary tabular-nums">
          {fmtMs(r.durationMs)}
        </span>
      )
    },
    {
      key: 'spanCount',
      label: 'Spans',
      width: '0.55fr',
      align: 'right',
      sortable: true,
      render: (r) => (
        <span className="text-sm font-mono text-text-muted tabular-nums">
          {r.spanCount}
        </span>
      )
    },
    {
      key: 'decision',
      label: 'Policy',
      width: '0.85fr',
      align: 'right',
      sortable: true,
      render: (r) => <DecisionBadge decision={r.decision} size="sm" />
    },
  ];

  return (
    <div className="ax-fade-in p-6 pt-5 pb-10 max-w-[1320px] mx-auto">
      <div className="flex items-end justify-between mb-4">
        <div>
          <h1 className="m-0 text-xl font-semibold tracking-tight">Traces</h1>
          <p className="m-0 mt-0.5 text-sm text-text-muted">
            {allTraces.length.toLocaleString()} traces · <span className="text-block-bright font-medium">{blockedTotal} with policy blocks</span> · {TIME_RANGES.find((t) => t.value === timeRange)?.label.toLowerCase()}
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="ghost"
            size="sm"
            icon="warn"
            onClick={() => setErrorMode(!errorMode)}
            active={errorMode}
          >
            {errorMode ? 'Clear error' : 'Simulate error'}
          </Button>
          <Button variant="secondary" size="sm" icon="refresh">Refresh</Button>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-2.5 mb-3.5 flex-wrap">
        <SearchInput
          value={query}
          onChange={setQuery}
          placeholder="Search name, trace_id, agent…"
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

      {errorMode ? (
        <Panel className="border-block-border">
          <ErrorState
            title="Failed to query traces"
            body="collector.query: connection refused (otlp:4317)"
            onRetry={() => setErrorMode(false)}
          />
        </Panel>
      ) : (
        <DataTable
          columns={columns}
          rows={pageRows}
          loading={loading}
          page={page}
          pageSize={pageSize}
          total={filteredTraces.length}
          onPage={setPage}
          sort={sort}
          onSort={(key) => setSort((s) => ({ key, dir: s.key === key && s.dir === 'desc' ? 'asc' : 'desc' }))}
          onRowClick={(r) => onOpenTrace(r)}
          rowKey={(r) => r.id}
          rowAccent={(r) => r.decision === 'block'}
        />
      )}
    </div>
  );
}
