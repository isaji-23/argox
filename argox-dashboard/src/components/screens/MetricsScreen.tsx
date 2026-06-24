import { useState, useEffect } from 'react';
import {
  AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, ReferenceLine
} from 'recharts';
import { api } from '../../lib/api';
import type { CostMetricsResponse, LatencyMetricsResponse, SuccessMetricsResponse } from '../../lib/api';
import { Panel, PanelHeader } from '../ui/Panel';
import { Skeleton, ErrorState } from '../ui/States';

interface MetricsScreenProps {
  timeRange: string;
}

const MODEL_COLORS = [
  'var(--peacock-cyan)',
  'var(--peacock-indigo)',
  'var(--gold)',
  'var(--peacock-teal)',
  'var(--bronze)',
];

export function MetricsScreen({ timeRange }: MetricsScreenProps) {
  const [costData, setCostData] = useState<CostMetricsResponse | null>(null);
  const [latencyData, setLatencyData] = useState<LatencyMetricsResponse | null>(null);
  const [successData, setSuccessData] = useState<SuccessMetricsResponse | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);

    const rangeMap: Record<string, number> = {
      '1h': 1,
      '24h': 24,
      '7d': 168,
      '30d': 720,
    };
    const windowHours = rangeMap[timeRange] || 24;

    try {
      const [costRes, latencyRes, successRes] = await Promise.all([
        api.getCostMetrics(windowHours),
        api.getLatencyMetrics(windowHours),
        api.getSuccessMetrics(windowHours),
      ]);
      setCostData(costRes);
      setLatencyData(latencyRes);
      setSuccessData(successRes);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch metrics');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [timeRange]);

  if (error) {
    return (
      <div className="flex h-full items-center justify-center p-6 bg-background">
        <ErrorState
          title="Metrics Fetch Error"
          body={error}
          onRetry={fetchData}
        />
      </div>
    );
  }

  if (loading || !costData || !latencyData || !successData) {
    return (
      <div className="p-6 space-y-6 max-w-[1600px] mx-auto bg-background">
        {/* KPI Grid Skeletons */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {[1, 2, 3].map((i) => (
            <Panel key={i} pad>
              <Skeleton h={16} w={80} className="mb-2" />
              <Skeleton h={32} w={120} className="mb-1" />
              <Skeleton h={14} w={160} />
            </Panel>
          ))}
        </div>

        {/* Charts Grid Skeletons */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {[1, 2, 3, 4].map((i) => (
            <Panel key={i} title="Loading Chart...">
              <div className="h-[250px] flex items-center justify-center">
                <Skeleton h="100%" w="100%" />
              </div>
            </Panel>
          ))}
          <Panel title="Loading Chart..." className="lg:col-span-2">
            <div className="h-[250px] flex items-center justify-center">
              <Skeleton h="100%" w="100%" />
            </div>
          </Panel>
        </div>
      </div>
    );
  }

  // --- Transform Stacked Cost Timeline ---
  // Array fields are defaulted to `[]` so a partial response (e.g. a Collector
  // version predating one of these fields) renders an empty chart instead of
  // crashing the whole screen on `.forEach`/`.map` of `undefined`.
  const costTimelineMap: Record<string, any> = {};
  const modelsSet = new Set<string>();
  (costData.timeline ?? []).forEach((pt) => {
    const label = new Date(pt.bucket).toLocaleString([], {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
    if (!costTimelineMap[pt.bucket]) {
      costTimelineMap[pt.bucket] = { name: label, bucket: pt.bucket };
    }
    costTimelineMap[pt.bucket][pt.model] = pt.cost;
    modelsSet.add(pt.model);
  });
  const formattedCostTimeline = Object.values(costTimelineMap).sort((a: any, b: any) =>
    new Date(a.bucket).getTime() - new Date(b.bucket).getTime()
  );
  const modelsList = Array.from(modelsSet);

  // --- Transform Latency Histogram ---
  const formattedHistogram = (latencyData.histogram ?? []).map((bin) => ({
    name: `${Math.round(bin.bin_min)}-${Math.round(bin.bin_max)}ms`,
    count: bin.count,
    bin_min: bin.bin_min,
    bin_max: bin.bin_max,
  }));

  const findBinIdx = (val: number) => {
    if (!formattedHistogram.length) return null;
    const idx = (latencyData.histogram ?? []).findIndex(
      (bin) => val >= bin.bin_min && val <= bin.bin_max
    );
    return idx !== -1 ? idx : null;
  };

  const p50BinIdx = findBinIdx(latencyData.percentiles.p50);
  const p95BinIdx = findBinIdx(latencyData.percentiles.p95);
  const p99BinIdx = findBinIdx(latencyData.percentiles.p99);

  // --- Transform Success Rate Timeline ---
  const formattedSuccessTimeline = (successData.timeline ?? []).map((pt) => ({
    name: new Date(pt.bucket).toLocaleString([], {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }),
    bucket: pt.bucket,
    rate: pt.success_rate !== null ? parseFloat((pt.success_rate * 100).toFixed(1)) : null,
    total: pt.total_runs,
  }));

  // --- Transform Top Agents ---
  const formattedAgents = (costData.top_agents ?? []).map((pt) => ({
    name: pt.agent_name,
    spend: parseFloat(pt.spend.toFixed(4)),
  }));

  // --- Transform Blocked Tools ---
  const formattedBlockedTools = (successData.top_blocked_tools ?? []).map((pt) => ({
    name: pt.tool_name,
    count: pt.blocked_count,
  }));

  return (
    <div className="p-6 space-y-6 max-w-[1600px] mx-auto bg-background animate-fade-in">
      {/* Definitions of gradients used in AreaCharts */}
      <svg className="absolute w-0 h-0" width="0" height="0">
        <defs>
          <linearGradient id="successGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="var(--allow)" stopOpacity={0.25} />
            <stop offset="95%" stopColor="var(--allow)" stopOpacity={0} />
          </linearGradient>
        </defs>
      </svg>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Panel pad className="relative overflow-hidden group hover:border-strong transition-all">
          <PanelHeader
            title="Total Spend"
            subtitle="Combined cost of LLM inference calls"
            icon="layers"
          />
          <div className="mt-4 flex items-baseline gap-2">
            <span className="text-3xl font-bold tracking-tight text-text-primary">
              ${costData.total_cost.toFixed(4)}
            </span>
          </div>
          <div className="mt-1.5 text-xs text-text-muted">
            Across {costData.trace_count} active traces
          </div>
        </Panel>

        <Panel pad className="relative overflow-hidden group hover:border-strong transition-all">
          <PanelHeader
            title="Median Latency"
            subtitle="P50 duration of root runs"
            icon="activity"
          />
          <div className="mt-4 flex items-baseline gap-2">
            <span className="text-3xl font-bold tracking-tight text-text-primary">
              {latencyData.trace_count === 0
                ? 'N/A'
                : latencyData.percentiles.p50 >= 1000
                ? (latencyData.percentiles.p50 / 1000).toFixed(2) + 's'
                : Math.round(latencyData.percentiles.p50) + 'ms'}
            </span>
          </div>
          <div className="mt-1.5 text-xs text-text-muted">
            P95: {latencyData.trace_count === 0
              ? 'N/A'
              : latencyData.p95_latency_ms >= 1000
              ? (latencyData.p95_latency_ms / 1000).toFixed(2) + 's'
              : Math.round(latencyData.p95_latency_ms) + 'ms'}
          </div>
        </Panel>

        <Panel pad className="relative overflow-hidden group hover:border-strong transition-all">
          <PanelHeader
            title="Success Rate"
            subtitle="Overall ratio of runs completing without failure"
            icon="check"
          />
          <div className="mt-4 flex items-baseline gap-2">
            <span className="text-3xl font-bold tracking-tight text-text-primary">
              {successData.success_rate !== null
                ? (successData.success_rate * 100).toFixed(1) + '%'
                : 'N/A'}
            </span>
          </div>
          <div className="mt-1.5 text-xs text-text-muted">
            {successData.successful_runs} / {successData.total_runs} runs successful
          </div>
        </Panel>
      </div>

      {/* 2-Column Responsive Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Chart 1: Stacked Cost by Model */}
        <Panel title="Total Cost Stacked by Model" pad>
          <div className="h-[280px] w-full">
            {formattedCostTimeline.length === 0 ? (
              <div className="h-full flex items-center justify-center text-text-muted text-sm">
                No model cost data within this window
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={formattedCostTimeline} margin={{ left: -10, right: 10, top: 10, bottom: 0 }}>
                  <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="3 3" />
                  <XAxis dataKey="name" stroke="var(--text-muted)" fontSize={11} />
                  <YAxis
                    stroke="var(--text-muted)"
                    fontSize={11}
                    tickFormatter={(val) => `$${val.toFixed(2)}`}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'var(--bg-overlay)',
                      borderColor: 'var(--border)',
                      borderRadius: 'var(--r-md)',
                      fontSize: '12px',
                    }}
                    labelStyle={{ fontWeight: 'bold', color: 'var(--text-primary)' }}
                  />
                  <Legend verticalAlign="bottom" height={36} iconType="circle" />
                  {modelsList.map((model, idx) => (
                    <Area
                      key={model}
                      type="monotone"
                      dataKey={model}
                      stackId="1"
                      stroke={MODEL_COLORS[idx % MODEL_COLORS.length]}
                      fill={MODEL_COLORS[idx % MODEL_COLORS.length]}
                      fillOpacity={0.4}
                    />
                  ))}
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </Panel>

        {/* Chart 2: Success Rate over time */}
        <Panel title="Success Ratio Over Time" pad>
          <div className="h-[280px] w-full">
            {formattedSuccessTimeline.length === 0 ? (
              <div className="h-full flex items-center justify-center text-text-muted text-sm">
                No runs data within this window
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={formattedSuccessTimeline} margin={{ left: -10, right: 10, top: 10, bottom: 0 }}>
                  <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="3 3" />
                  <XAxis dataKey="name" stroke="var(--text-muted)" fontSize={11} />
                  <YAxis
                    stroke="var(--text-muted)"
                    fontSize={11}
                    tickFormatter={(val) => `${val}%`}
                    domain={[0, 100]}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'var(--bg-overlay)',
                      borderColor: 'var(--border)',
                      borderRadius: 'var(--r-md)',
                      fontSize: '12px',
                    }}
                    labelStyle={{ fontWeight: 'bold', color: 'var(--text-primary)' }}
                  />
                  <Area
                    type="monotone"
                    dataKey="rate"
                    name="Success Rate"
                    stroke="var(--allow)"
                    fill="url(#successGrad)"
                    strokeWidth={2}
                    connectNulls
                  />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </Panel>

        {/* Chart 3: Latency Distribution (Histogram) */}
        <Panel title="Latency Distribution (Root Runs)" pad>
          <div className="h-[280px] w-full">
            {formattedHistogram.length === 0 ? (
              <div className="h-full flex items-center justify-center text-text-muted text-sm">
                No run latency data within this window
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={formattedHistogram} margin={{ left: -10, right: 10, top: 10, bottom: 0 }}>
                  <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="3 3" />
                  <XAxis dataKey="name" stroke="var(--text-muted)" fontSize={10} />
                  <YAxis stroke="var(--text-muted)" fontSize={11} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'var(--bg-overlay)',
                      borderColor: 'var(--border)',
                      borderRadius: 'var(--r-md)',
                      fontSize: '12px',
                    }}
                    labelStyle={{ fontWeight: 'bold', color: 'var(--text-primary)' }}
                  />
                  <Bar
                    dataKey="count"
                    name="Run Count"
                    fill="var(--peacock-indigo)"
                    radius={[4, 4, 0, 0]}
                  />
                  {p50BinIdx !== null && formattedHistogram[p50BinIdx] && (
                    <ReferenceLine
                      x={formattedHistogram[p50BinIdx].name}
                      stroke="var(--peacock-teal)"
                      strokeWidth={1.5}
                      strokeDasharray="3 3"
                      label={{ value: 'P50', fill: 'var(--peacock-teal)', fontSize: 10, position: 'top' }}
                    />
                  )}
                  {p95BinIdx !== null && formattedHistogram[p95BinIdx] && (
                    <ReferenceLine
                      x={formattedHistogram[p95BinIdx].name}
                      stroke="var(--gold)"
                      strokeWidth={1.5}
                      strokeDasharray="3 3"
                      label={{ value: 'P95', fill: 'var(--gold)', fontSize: 10, position: 'top' }}
                    />
                  )}
                  {p99BinIdx !== null && formattedHistogram[p99BinIdx] && (
                    <ReferenceLine
                      x={formattedHistogram[p99BinIdx].name}
                      stroke="var(--block)"
                      strokeWidth={1.5}
                      strokeDasharray="3 3"
                      label={{ value: 'P99', fill: 'var(--block)', fontSize: 10, position: 'top' }}
                    />
                  )}
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </Panel>

        {/* Chart 4: Top Agents by Spend */}
        <Panel title="Top Agents by Spend" pad>
          <div className="h-[280px] w-full">
            {formattedAgents.length === 0 ? (
              <div className="h-full flex items-center justify-center text-text-muted text-sm">
                No agent spend data within this window
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={formattedAgents}
                  layout="vertical"
                  margin={{ left: 20, right: 10, top: 10, bottom: 0 }}
                >
                  <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="3 3" />
                  <XAxis
                    type="number"
                    stroke="var(--text-muted)"
                    fontSize={11}
                    tickFormatter={(val) => `$${val.toFixed(2)}`}
                  />
                  <YAxis type="category" dataKey="name" stroke="var(--text-muted)" fontSize={11} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'var(--bg-overlay)',
                      borderColor: 'var(--border)',
                      borderRadius: 'var(--r-md)',
                      fontSize: '12px',
                    }}
                    labelStyle={{ fontWeight: 'bold', color: 'var(--text-primary)' }}
                  />
                  <Bar
                    dataKey="spend"
                    name="Spend (USD)"
                    fill="var(--peacock-cyan)"
                    radius={[0, 4, 4, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </Panel>

        {/* Chart 5: Top Blocked Tools */}
        <Panel title="Top Blocked Tools (Policy Violations)" className="lg:col-span-2" pad>
          <div className="h-[280px] w-full">
            {formattedBlockedTools.length === 0 ? (
              <div className="h-full flex items-center justify-center text-text-muted text-sm">
                No tool block operations occurred within this window
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={formattedBlockedTools}
                  layout="vertical"
                  margin={{ left: 20, right: 10, top: 10, bottom: 0 }}
                >
                  <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="3 3" />
                  <XAxis type="number" stroke="var(--text-muted)" fontSize={11} />
                  <YAxis type="category" dataKey="name" stroke="var(--text-muted)" fontSize={11} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'var(--bg-overlay)',
                      borderColor: 'var(--border)',
                      borderRadius: 'var(--r-md)',
                      fontSize: '12px',
                    }}
                    labelStyle={{ fontWeight: 'bold', color: 'var(--text-primary)' }}
                  />
                  <Bar
                    dataKey="count"
                    name="Blocks Count"
                    fill="var(--block)"
                    radius={[0, 4, 4, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}
