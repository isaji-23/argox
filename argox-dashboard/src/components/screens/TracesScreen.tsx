// Traces list: searchable, filterable, paginated table backed by GET /traces.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useShell } from '../../App';
import { api, type TraceSummary } from '../../lib/api';
import { rangeToHours, rangeLabel } from '../../lib/timeRange';
import { fmtMs, fmtUsd, fmtNum } from '../../lib/utils';
import { Panel } from '../ui/Panel';
import { Button } from '../ui/Button';
import { Badge, DecisionBadge, StatusDot } from '../ui/Badge';
import { Icon } from '../shared/Icon';
import { SearchInput } from '../ui/SearchInput';
import { Select } from '../ui/Select';
import { DataTable, type Column, type SortState } from '../ui/DataTable';
import { ErrorState } from '../ui/States';

const PAGE_SIZE = 10;

// Frontend sort key -> Collector `sort` field.
const SORT_FIELD: Record<string, string> = {
  start_time: 'start_time',
  total_duration_ms: 'duration',
  total_cost: 'cost',
  span_count: 'spans',
};

function FilterSelect({ label, value, options, onChange }: { label: string; value: string; options: { value: string; label: string }[]; onChange: (v: string) => void }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', border: '1px solid var(--border-strong)', borderRadius: 'var(--r-md)', background: 'var(--bg-surface-3)' }}>
      <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-muted)', padding: '0 2px 0 10px', whiteSpace: 'nowrap' }}>{label}</span>
      <Select value={value} options={options} onChange={onChange} minWidth={96} size="sm" />
    </div>
  );
}

export function TracesScreen() {
  const { timeRange, agent, reloadKey } = useShell();
  const navigate = useNavigate();

  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<SortState>({ key: 'start_time', dir: 'desc' });
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [fStatus, setFStatus] = useState('all');
  const [fDecision, setFDecision] = useState('all');
  const [fAgent, setFAgent] = useState('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => setFAgent(agent === 'all' ? 'all' : agent), [agent]);

  // Debounce the trace-id search (300ms).
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(query), 300);
    return () => clearTimeout(t);
  }, [query]);

  // Reset to first page on any filter/search/sort/range change.
  useEffect(() => setPage(1), [debouncedQuery, fStatus, fDecision, fAgent, sort, timeRange]);

  const load = useCallback(() => {
    setLoading(true);
    setError(false);
    api
      .listTraces({
        skip: (page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
        trace_id: debouncedQuery || undefined,
        agent_name: fAgent,
        status: fStatus,
        decision: fDecision,
        sort: `${SORT_FIELD[sort.key] ?? 'start_time'}:${sort.dir}`,
        window_hours: rangeToHours(timeRange),
      })
      .then((res) => {
        setTraces(res.items);
        setTotal(res.total);
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [page, debouncedQuery, fAgent, fStatus, fDecision, sort, timeRange]);

  useEffect(() => {
    load();
  }, [load, reloadKey]);

  const onSort = (key: string) =>
    setSort((s) => ({ key, dir: s.key === key && s.dir === 'desc' ? 'asc' : 'desc' }));

  const filtersActive = fStatus !== 'all' || fDecision !== 'all' || fAgent !== 'all' || query !== '';
  const clearFilters = () => {
    setQuery('');
    setFStatus('all');
    setFDecision('all');
    setFAgent('all');
  };

  const columns: Column<TraceSummary>[] = useMemo(
    () => [
      {
        key: 'trace_id',
        label: 'Trace ID',
        width: '1.6fr',
        render: (r) => (
          <div style={{ display: 'flex', alignItems: 'center', gap: 9, minWidth: 0 }}>
            <StatusDot status={r.status} />
            <div style={{ minWidth: 0 }}>
              <div
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 'var(--fs-sm)',
                  fontWeight: 550,
                  color: r.status === 'error' ? 'var(--block-ink)' : 'var(--text-primary)',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {r.trace_id}
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-2xs)', color: 'var(--text-faint)' }}>{r.agent_version}</div>
            </div>
          </div>
        ),
      },
      {
        key: 'agent_name',
        label: 'Agent',
        width: '1fr',
        render: (r) => (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 'var(--fs-sm)', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
            <Icon name="bolt" size={12} style={{ color: 'var(--text-faint)' }} />
            {r.agent_name}
          </span>
        ),
      },
      {
        key: 'start_time',
        label: 'Started',
        width: '1fr',
        sortable: true,
        render: (r) => (
          <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            {new Date(r.start_time).toLocaleString('en-US', { hour12: false })}
          </span>
        ),
      },
      {
        key: 'total_duration_ms',
        label: 'Duration',
        width: '0.8fr',
        sortable: true,
        render: (r) => (
          <span className="tnum" style={{ fontSize: 'var(--fs-sm)', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
            {fmtMs(r.total_duration_ms)}
          </span>
        ),
      },
      {
        key: 'span_count',
        label: 'Spans',
        width: '0.55fr',
        sortable: true,
        render: (r) => (
          <span className="tnum" style={{ fontSize: 'var(--fs-sm)', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
            {r.span_count}
          </span>
        ),
      },
      {
        key: 'total_cost',
        label: 'Cost',
        width: '0.7fr',
        sortable: true,
        render: (r) => (
          <span className="tnum" style={{ fontSize: 'var(--fs-sm)', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
            {fmtUsd(r.total_cost)}
          </span>
        ),
      },
      {
        key: 'decision',
        label: 'Policy',
        width: '0.85fr',
        render: (r) => <DecisionBadge decision={r.decision} size="sm" />,
      },
      {
        key: 'status',
        label: 'Result',
        width: '0.7fr',
        render: (r) => (
          <Badge tone={r.status === 'error' ? 'error' : 'allow'}>
            {r.status === 'error' ? 'Error' : 'Success'}
          </Badge>
        ),
      },
    ],
    [],
  );

  return (
    <div className="ax-fade-in" style={{ padding: '18px 22px 40px', maxWidth: 1320, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 'var(--fs-xl)', fontWeight: 600, letterSpacing: '-0.015em' }}>Traces</h1>
          <p style={{ margin: '3px 0 0', fontSize: 'var(--fs-sm)', color: 'var(--text-muted)' }}>
            {fmtNum(total)} traces · {rangeLabel(timeRange).toLowerCase()}
          </p>
        </div>
        <Button variant="secondary" size="sm" icon="refresh" onClick={load}>
          Refresh
        </Button>
      </div>

      {/* Filter bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
        <SearchInput value={query} onChange={setQuery} placeholder="Search trace_id…" width={280} />
        <div style={{ width: 1, height: 22, background: 'var(--border)' }} />
        <FilterSelect
          label="Agent"
          value={fAgent}
          onChange={setFAgent}
          options={[{ value: 'all', label: 'All' }, ...(fAgent !== 'all' ? [{ value: fAgent, label: fAgent }] : [])]}
        />
        <FilterSelect
          label="Status"
          value={fStatus}
          onChange={setFStatus}
          options={[{ value: 'all', label: 'All' }, { value: 'ok', label: 'OK' }, { value: 'error', label: 'Error' }]}
        />
        <FilterSelect
          label="Decision"
          value={fDecision}
          onChange={setFDecision}
          options={[{ value: 'all', label: 'All' }, { value: 'allow', label: 'Allow' }, { value: 'warn', label: 'Warn' }, { value: 'block', label: 'Block' }]}
        />
        {filtersActive && (
          <Button variant="ghost" size="sm" icon="x" onClick={clearFilters}>
            Clear
          </Button>
        )}
      </div>

      {error ? (
        <Panel>
          <ErrorState title="Failed to query traces" body="collector.query: request failed" onRetry={load} />
        </Panel>
      ) : (
        <DataTable
          columns={columns}
          rows={traces}
          loading={loading}
          page={page}
          pageSize={PAGE_SIZE}
          total={total}
          onPage={setPage}
          sort={sort}
          onSort={onSort}
          onRowClick={(r) => navigate(`/traces/${encodeURIComponent(r.trace_id)}`)}
          rowKey={(r) => r.trace_id}
          rowAccent={(r) => r.status === 'error'}
          empty={{ icon: 'traces', title: 'No traces match these filters', body: 'Try widening the time range or clearing the status / decision filters.' }}
        />
      )}
    </div>
  );
}
