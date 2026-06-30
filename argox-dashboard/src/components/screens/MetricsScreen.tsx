// Metrics dashboard: cost / latency / success over the selected window.
// Three read-scope calls run in parallel and feed the five charts + KPI row.
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useShell } from '../../App';
import {
  api,
  type CostMetricsResponse,
  type LatencyMetricsResponse,
  type SuccessMetricsResponse,
} from '../../lib/api';
import { rangeToHours, rangeLabel } from '../../lib/timeRange';
import { fmtUsd, fmtNum, fmtMs } from '../../lib/utils';
import { Panel, PanelHeader } from '../ui/Panel';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { Icon, type IconName } from '../shared/Icon';
import { ChartSkeleton, ErrorState } from '../ui/States';
import { StackedTimeChart, Histogram, SuccessChart, HBarChart, ChartLegend, MODEL_COLORS, type StackPoint, type HistogramBin } from '../charts';

function bucketLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
}

function KpiCard({
  label,
  value,
  icon,
  tone,
  loading,
}: {
  label: string;
  value: ReactNode;
  icon: IconName;
  tone?: 'block';
  loading?: boolean;
}) {
  const blocked = tone === 'block';
  return (
    <div
      style={{
        padding: '13px 15px',
        borderRadius: 'var(--r-lg)',
        background: 'var(--bg-surface)',
        border: '1px solid ' + (blocked ? 'var(--block-border)' : 'var(--border)'),
        borderLeft: blocked ? '2.5px solid var(--block-edge)' : '1px solid var(--border)',
        boxShadow: 'var(--shadow-sm)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 9, color: blocked ? 'var(--block-bright)' : 'var(--text-muted)' }}>
        <Icon name={icon} size={14} />
        <span style={{ fontSize: 'var(--fs-2xs)', fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase' }}>{label}</span>
      </div>
      <span
        className="tnum"
        style={{
          fontSize: 'var(--fs-2xl)',
          fontWeight: 600,
          fontFamily: 'var(--font-display)',
          letterSpacing: '-0.02em',
          color: blocked ? 'var(--block-ink)' : 'var(--text-primary)',
          lineHeight: 1,
        }}
      >
        {loading ? '—' : value}
      </span>
    </div>
  );
}

function ChartPanel({
  title,
  subtitle,
  icon,
  right,
  loading,
  error,
  onRetry,
  children,
  height = 188,
}: {
  title: string;
  subtitle: string;
  icon: IconName;
  right?: ReactNode;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  children: ReactNode;
  height?: number;
}) {
  return (
    <Panel style={{ minWidth: 0 }}>
      <PanelHeader title={title} subtitle={subtitle} icon={icon} right={right} />
      <div style={{ marginTop: 14 }}>
        {error ? (
          <ErrorState title="Query failed" body="collector: request failed" onRetry={onRetry} />
        ) : loading ? (
          <ChartSkeleton height={height} />
        ) : (
          children
        )}
      </div>
    </Panel>
  );
}

export function MetricsScreen() {
  const { timeRange, reloadKey } = useShell();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [cost, setCost] = useState<CostMetricsResponse | null>(null);
  const [latency, setLatency] = useState<LatencyMetricsResponse | null>(null);
  const [success, setSuccess] = useState<SuccessMetricsResponse | null>(null);

  const load = useCallback(() => {
    const hours = rangeToHours(timeRange);
    setLoading(true);
    setError(false);
    Promise.all([api.getCostMetrics(hours), api.getLatencyMetrics(hours), api.getSuccessMetrics(hours)])
      .then(([c, l, s]) => {
        setCost(c);
        setLatency(l);
        setSuccess(s);
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [timeRange]);

  useEffect(() => {
    load();
  }, [load, reloadKey]);

  // --- derive chart series ---
  const { costData, costKeys } = useMemo(() => {
    const rows = cost?.timeline ?? [];
    const buckets: string[] = [];
    const models = new Set<string>();
    const byBucket = new Map<string, StackPoint>();
    for (const r of rows) {
      models.add(r.model);
      if (!byBucket.has(r.bucket)) {
        byBucket.set(r.bucket, { label: bucketLabel(r.bucket) });
        buckets.push(r.bucket);
      }
      const point = byBucket.get(r.bucket)!;
      point[r.model] = ((point[r.model] as number) || 0) + r.cost;
    }
    const keys = [...models];
    const data = buckets.map((b) => {
      const p = byBucket.get(b)!;
      for (const k of keys) if (p[k] === undefined) p[k] = 0;
      return p;
    });
    return { costData: data, costKeys: keys };
  }, [cost]);

  const { histData, markers } = useMemo(() => {
    const bins = latency?.histogram ?? [];
    const data: HistogramBin[] = bins.map((b) => ({ label: fmtMs(b.bin_max), count: b.count }));
    const pct = latency?.percentiles ?? {
      p50: latency?.avg_latency_ms ?? 0,
      p95: latency?.p95_latency_ms ?? 0,
      p99: (latency?.p95_latency_ms ?? 0) * 1.2,
    };
    const idxFor = (ms: number) => {
      for (let i = 0; i < bins.length; i++) if (ms <= bins[i].bin_max) return i;
      return Math.max(0, bins.length - 1);
    };
    return { histData: data, markers: { p50: idxFor(pct.p50), p95: idxFor(pct.p95), p99: idxFor(pct.p99) } };
  }, [latency]);

  const successData: StackPoint[] = useMemo(
    () =>
      (success?.timeline ?? []).map((t) => ({
        label: bucketLabel(t.bucket),
        success: t.successful_runs,
        error: Math.max(t.total_runs - t.successful_runs, 0),
        blocked: 0,
      })),
    [success],
  );

  const topAgents = useMemo(() => (cost?.top_agents ?? []).map((a) => ({ agent: a.agent_name, spend: a.spend })), [cost]);
  const blockedTools = useMemo(
    () => (success?.top_blocked_tools ?? []).map((t) => ({ tool: t.tool_name, count: t.blocked_count })),
    [success],
  );
  const totalBlocks = blockedTools.reduce((s, t) => s + t.count, 0);

  const successRate = success?.success_rate != null ? (success.success_rate * 100).toFixed(1) + '%' : '—';
  const p95 = latency?.percentiles?.p95 ?? latency?.p95_latency_ms ?? 0;

  return (
    <div className="ax-fade-in" style={{ padding: '18px 22px 40px', maxWidth: 1320, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 'var(--fs-xl)', fontWeight: 600, letterSpacing: '-0.015em' }}>Metrics</h1>
          <p style={{ margin: '3px 0 0', fontSize: 'var(--fs-sm)', color: 'var(--text-muted)' }}>
            Cost, latency and policy enforcement across all agents · {rangeLabel(timeRange).toLowerCase()}
          </p>
        </div>
        <Button variant="secondary" size="sm" icon="refresh" onClick={load}>
          Refresh
        </Button>
      </div>

      {/* KPIs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 14 }}>
        <KpiCard label="Total cost" value={fmtUsd(cost?.total_cost ?? 0)} icon="dollar" loading={loading} />
        <KpiCard label="Requests" value={fmtNum(cost?.trace_count ?? success?.total_runs ?? 0)} icon="spark" loading={loading} />
        <KpiCard label="Success rate" value={successRate} icon="check" loading={loading} />
        <KpiCard label="P95 latency" value={fmtMs(p95)} icon="gauge" loading={loading} />
        <KpiCard label="Policy blocks" value={fmtNum(totalBlocks)} icon="ban" tone="block" loading={loading} />
      </div>

      {/* Cost by model — full width */}
      <div style={{ marginBottom: 14 }}>
        <ChartPanel
          title="Total cost by model"
          subtitle="Stacked spend per time bucket"
          icon="dollar"
          loading={loading}
          error={error}
          onRetry={load}
          height={220}
          right={<ChartLegend items={costKeys.map((k, i) => ({ label: k, color: MODEL_COLORS[k] || ['var(--span-llm)', 'var(--span-tool)', 'var(--span-processor)', 'var(--gold)'][i % 4] }))} />}
        >
          <StackedTimeChart data={costData} keys={costKeys} colors={MODEL_COLORS} height={220} valuePrefix="$" />
        </ChartPanel>
      </div>

      {/* Latency + success */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.25fr 1fr', gap: 14, marginBottom: 14 }}>
        <ChartPanel title="Latency distribution" subtitle="Request duration with percentile markers" icon="gauge" loading={loading} error={error} onRetry={load}>
          <Histogram data={histData} markers={markers} />
        </ChartPanel>
        <ChartPanel
          title="Success ratio"
          subtitle="Successful vs error runs over time"
          icon="check"
          loading={loading}
          error={error}
          onRetry={load}
          right={<ChartLegend items={[{ label: 'Success', color: 'var(--allow)' }, { label: 'Error', color: 'var(--text-faint)' }]} />}
        >
          <SuccessChart data={successData} />
        </ChartPanel>
      </div>

      {/* Top agents + blocked tools */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        <ChartPanel title="Top agents by spend" subtitle="Highest-cost agents this period" icon="bolt" loading={loading} error={error} onRetry={load}>
          <HBarChart data={topAgents} labelKey="agent" valueKey="spend" color="var(--accent)" valueFmt={(v) => '$' + v.toFixed(0)} />
        </ChartPanel>
        <ChartPanel
          title="Top blocked tools"
          subtitle="Most-denied tool calls by policy"
          icon="ban"
          loading={loading}
          error={error}
          onRetry={load}
          right={<Badge tone="block" mono>{fmtNum(totalBlocks)} blocks</Badge>}
        >
          <HBarChart data={blockedTools} labelKey="tool" valueKey="count" blockTone valueFmt={fmtNum} />
        </ChartPanel>
      </div>
    </div>
  );
}
