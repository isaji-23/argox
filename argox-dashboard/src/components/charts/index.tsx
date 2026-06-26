// SVG charts (peacock-iridescent, responsive) — ported from argox-design.
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useMeasure } from './useMeasure';
import { fmtNum } from '../../lib/utils';

/** Default model -> colour mapping for the cost chart. */
export const MODEL_COLORS: Record<string, string> = {
  'gpt-4o': 'var(--span-llm)',
  'claude-3.7-sonnet': 'var(--span-tool)',
  'gpt-4o-mini': 'var(--span-processor)',
  'llama-3.3-70b': 'var(--gold)',
};

const PALETTE = ['var(--span-llm)', 'var(--span-tool)', 'var(--span-processor)', 'var(--gold)', 'var(--accent)'];

// Follows the cursor via fixed positioning through a portal, so it tracks the
// mouse and is never clipped by the chart container's overflow or the panel
// edge. Flips to the other side of the cursor near the viewport boundary.
function ChartTooltip({ cx, cy, children }: { cx: number | null; cy: number | null; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: 0, top: 0 });

  useLayoutEffect(() => {
    if (cx == null || cy == null || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const GAP = 14;
    const M = 8;
    let left = cx + GAP;
    let top = cy + GAP;
    if (left + r.width > vw - M) left = cx - GAP - r.width;
    if (top + r.height > vh - M) top = cy - GAP - r.height;
    setPos({ left: Math.max(M, left), top: Math.max(M, top) });
  }, [cx, cy, children]);

  if (cx == null || cy == null) return null;

  return createPortal(
    <div
      ref={ref}
      style={{
        position: 'fixed',
        left: pos.left,
        top: pos.top,
        pointerEvents: 'none',
        background: 'var(--bg-overlay)',
        border: '1px solid var(--border-strong)',
        borderRadius: 'var(--r-sm)',
        boxShadow: 'var(--shadow-pop)',
        padding: '7px 9px',
        fontSize: 'var(--fs-xs)',
        zIndex: 3000,
        minWidth: 120,
      }}
    >
      {children}
    </div>,
    document.body,
  );
}

export interface StackPoint {
  label: string;
  [key: string]: number | string;
}

interface StackedTimeChartProps {
  data: StackPoint[];
  keys: string[];
  colors?: Record<string, string>;
  height?: number;
  variant?: 'area' | 'bars';
  valuePrefix?: string;
}

export function StackedTimeChart({
  data,
  keys,
  colors = {},
  height = 188,
  variant = 'area',
  valuePrefix = '$',
}: StackedTimeChartProps) {
  const [ref, W] = useMeasure();
  const [hover, setHover] = useState<number | null>(null);
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null);
  const padL = 44, padR = 12, padT = 12, padB = 24;
  const iw = Math.max(W - padL - padR, 10), ih = height - padT - padB;
  const colorOf = (k: string, i: number) => colors[k] || PALETTE[i % PALETTE.length];
  const val = (d: StackPoint, k: string) => (d[k] as number) || 0;
  const totals = data.map((d) => keys.reduce((s, k) => s + val(d, k), 0));
  const maxY = Math.max(...totals, 1) * 1.1;
  const x = (i: number) => padL + (data.length <= 1 ? iw / 2 : (i / (data.length - 1)) * iw);
  const xBand = (i: number) => padL + (i + 0.5) * (iw / Math.max(data.length, 1));
  const y = (v: number) => padT + ih - (v / maxY) * ih;
  const yTicks = 4;

  const layers: { k: string; color: string; lower: number[]; upper: number[] }[] = [];
  let acc = data.map(() => 0);
  keys.forEach((k, ki) => {
    const lower = acc.slice();
    const upper = data.map((d, i) => lower[i] + val(d, k));
    acc = upper;
    layers.push({ k, color: colorOf(k, ki), lower, upper });
  });

  if (data.length === 0) {
    return <div ref={ref} style={{ height, display: 'grid', placeItems: 'center', color: 'var(--text-faint)', fontSize: 'var(--fs-xs)' }}>No data in this window</div>;
  }

  return (
    <div ref={ref} style={{ position: 'relative', width: '100%', minWidth: 0, overflow: 'hidden' }}>
      <svg
        width={W}
        height={height}
        style={{ display: 'block' }}
        onMouseLeave={() => { setHover(null); setCursor(null); }}
        onMouseMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const mx = e.clientX - rect.left;
          let idx = Math.round(((mx - padL) / iw) * (data.length - 1));
          idx = Math.max(0, Math.min(data.length - 1, idx));
          setHover(idx);
          setCursor({ x: e.clientX, y: e.clientY });
        }}
      >
        {Array.from({ length: yTicks + 1 }).map((_, i) => {
          const v = (maxY / yTicks) * i;
          return (
            <g key={i}>
              <line x1={padL} x2={W - padR} y1={y(v)} y2={y(v)} stroke="var(--chart-grid)" strokeWidth="1" />
              <text x={padL - 8} y={y(v) + 3} textAnchor="end" fontSize="9.5" fill="var(--text-faint)" fontFamily="var(--font-mono)">
                {valuePrefix}
                {v.toFixed(0)}
              </text>
            </g>
          );
        })}
        {data.map((d, i) =>
          i % Math.ceil(data.length / 8) === 0 ? (
            <text key={i} x={x(i)} y={height - 7} textAnchor="middle" fontSize="9.5" fill="var(--text-faint)" fontFamily="var(--font-mono)">
              {d.label}
            </text>
          ) : null,
        )}

        {variant === 'area'
          ? layers.map((L, li) => {
              const top = L.upper.map((v, i) => `${x(i)},${y(v)}`).join(' ');
              const bot = L.lower
                .map((v, i) => `${x(i)},${y(v)}`)
                .reverse()
                .join(' ');
              return <polygon key={li} points={`${top} ${bot}`} fill={L.color} fillOpacity={0.72} stroke={L.color} strokeWidth="1" strokeOpacity="0.9" />;
            })
          : layers.map((L, li) =>
              data.map((_, i) => {
                const bw = (iw / data.length) * 0.62;
                return (
                  <rect
                    key={li + '-' + i}
                    x={xBand(i) - bw / 2}
                    y={y(L.upper[i])}
                    width={bw}
                    height={Math.max(y(L.lower[i]) - y(L.upper[i]), 0)}
                    fill={L.color}
                    fillOpacity={0.9}
                    rx="1.5"
                  />
                );
              }),
            )}

        {hover != null && (
          <line x1={x(hover)} x2={x(hover)} y1={padT} y2={padT + ih} stroke="var(--accent)" strokeWidth="1" strokeOpacity="0.5" strokeDasharray="3 3" />
        )}
        {hover != null &&
          layers.map((L, ki) => (
            <circle key={L.k} cx={x(hover)} cy={y(L.upper[hover])} r="2.6" fill={colorOf(L.k, ki)} stroke="var(--bg-surface)" strokeWidth="1.5" />
          ))}
      </svg>
      {hover != null && (
        <ChartTooltip cx={cursor?.x ?? null} cy={cursor?.y ?? null}>
          <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', marginBottom: 4 }}>{data[hover].label}</div>
          {keys.map((k, ki) => (
            <div key={k} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, color: 'var(--text-secondary)' }}>
                <span style={{ width: 8, height: 8, borderRadius: 2, background: colorOf(k, ki) }} />
                {k}
              </span>
              <span className="tnum" style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                {valuePrefix}
                {val(data[hover], k).toFixed(2)}
              </span>
            </div>
          ))}
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginTop: 4, paddingTop: 4, borderTop: '1px solid var(--border)' }}>
            <span style={{ color: 'var(--text-muted)' }}>Total</span>
            <span className="tnum" style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)', fontWeight: 600 }}>
              {valuePrefix}
              {totals[hover].toFixed(2)}
            </span>
          </div>
        </ChartTooltip>
      )}
    </div>
  );
}

export interface HistogramBin {
  label: string;
  count: number;
}

interface HistogramProps {
  data: HistogramBin[];
  markers: { p50: number; p95: number; p99: number };
  height?: number;
}

export function Histogram({ data, markers, height = 188 }: HistogramProps) {
  const [ref, W] = useMeasure();
  const [hover, setHover] = useState<number | null>(null);
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null);
  const padL = 40, padR = 12, padT = 22, padB = 26;
  const iw = Math.max(W - padL - padR, 10), ih = height - padT - padB;
  const maxY = Math.max(...data.map((d) => d.count), 1) * 1.12;
  const bw = iw / Math.max(data.length, 1);
  const y = (v: number) => padT + ih - (v / maxY) * ih;
  const colorFor = (i: number) => {
    if (i >= markers.p99) return 'var(--block)';
    if (i >= markers.p95) return 'var(--warn)';
    if (i >= markers.p50) return 'var(--span-processor)';
    return 'var(--span-llm)';
  };
  const markerLine = (idx: number, label: string, color: string) => {
    const mx = padL + (idx + 0.5) * bw;
    return (
      <g key={label}>
        <line x1={mx} x2={mx} y1={padT - 6} y2={padT + ih} stroke={color} strokeWidth="1.4" strokeDasharray="4 3" />
        <rect x={mx - 16} y={padT - 18} width="32" height="13" rx="3" fill={color} />
        <text x={mx} y={padT - 8} textAnchor="middle" fontSize="9" fontWeight="700" fill="var(--bg-base)" fontFamily="var(--font-mono)">
          {label}
        </text>
      </g>
    );
  };

  if (data.length === 0) {
    return <div ref={ref} style={{ height, display: 'grid', placeItems: 'center', color: 'var(--text-faint)', fontSize: 'var(--fs-xs)' }}>No latency samples</div>;
  }

  return (
    <div ref={ref} style={{ position: 'relative', width: '100%', minWidth: 0, overflow: 'hidden' }}>
      <svg
        width={W}
        height={height}
        style={{ display: 'block' }}
        onMouseLeave={() => { setHover(null); setCursor(null); }}
        onMouseMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          let idx = Math.floor((e.clientX - rect.left - padL) / bw);
          idx = Math.max(0, Math.min(data.length - 1, idx));
          setHover(idx);
          setCursor({ x: e.clientX, y: e.clientY });
        }}
      >
        {Array.from({ length: 4 }).map((_, i) => {
          const v = (maxY / 3) * i;
          return (
            <g key={i}>
              <line x1={padL} x2={W - padR} y1={y(v)} y2={y(v)} stroke="var(--chart-grid)" strokeWidth="1" />
              <text x={padL - 7} y={y(v) + 3} textAnchor="end" fontSize="9.5" fill="var(--text-faint)" fontFamily="var(--font-mono)">
                {v >= 1000 ? (v / 1000).toFixed(1) + 'k' : v.toFixed(0)}
              </text>
            </g>
          );
        })}
        {data.map((d, i) => (
          <g key={i} onMouseEnter={() => setHover(i)}>
            <rect
              x={padL + i * bw + bw * 0.12}
              y={y(d.count)}
              width={bw * 0.76}
              height={padT + ih - y(d.count)}
              fill={colorFor(i)}
              fillOpacity={hover === i ? 1 : 0.82}
              rx="2"
            />
            <text x={padL + i * bw + bw / 2} y={height - 8} textAnchor="middle" fontSize="8.5" fill="var(--text-faint)" fontFamily="var(--font-mono)">
              {d.label}
            </text>
          </g>
        ))}
        {markerLine(markers.p50, 'P50', 'var(--text-secondary)')}
        {markerLine(markers.p95, 'P95', 'var(--warn)')}
        {markerLine(markers.p99, 'P99', 'var(--block)')}
      </svg>
      {hover != null && (
        <ChartTooltip cx={cursor?.x ?? null} cy={cursor?.y ?? null}>
          <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>{data[hover].label}</div>
          <div className="tnum" style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)', fontWeight: 600 }}>
            {fmtNum(data[hover].count)} reqs
          </div>
        </ChartTooltip>
      )}
    </div>
  );
}

export function SuccessChart({ data, height = 188 }: { data: StackPoint[]; height?: number }) {
  return (
    <StackedTimeChart
      data={data}
      keys={['success', 'error', 'blocked']}
      colors={{ success: 'var(--allow)', error: 'var(--text-faint)', blocked: 'var(--block)' }}
      height={height}
      variant="area"
      valuePrefix=""
    />
  );
}

interface HBarChartProps {
  data: Record<string, string | number>[];
  labelKey: string;
  valueKey: string;
  color?: string;
  valueFmt?: (v: number) => string;
  height?: number;
  blockTone?: boolean;
}

export function HBarChart({
  data,
  labelKey,
  valueKey,
  color = 'var(--accent)',
  valueFmt = (v) => String(v),
  height = 188,
  blockTone = false,
}: HBarChartProps) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(...data.map((d) => Number(d[valueKey]) || 0), 1) * 1.04;
  const rowH = Math.min(30, (height - 8) / Math.max(data.length, 1));

  if (data.length === 0) {
    return <div style={{ height, display: 'grid', placeItems: 'center', color: 'var(--text-faint)', fontSize: 'var(--fs-xs)' }}>No data</div>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 6, height, paddingTop: 2 }}>
      {data.map((d, i) => {
        const v = Number(d[valueKey]) || 0;
        const pct = (v / max) * 100;
        const c = blockTone ? (i === 0 ? 'var(--block)' : i === 1 ? 'var(--block-bright)' : 'var(--warn)') : color;
        return (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10 }} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            <span
              style={{
                flex: '0 0 116px',
                fontSize: 'var(--fs-xs)',
                fontFamily: 'var(--font-mono)',
                color: 'var(--text-secondary)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                textAlign: 'right',
              }}
            >
              {String(d[labelKey])}
            </span>
            <div style={{ flex: 1, height: Math.max(rowH - 12, 14), background: 'var(--bg-surface-2)', borderRadius: 'var(--r-xs)', position: 'relative', overflow: 'hidden' }}>
              <div
                style={{
                  position: 'absolute',
                  left: 0,
                  top: 0,
                  bottom: 0,
                  width: `${pct}%`,
                  background: c,
                  opacity: hover === i ? 1 : 0.85,
                  borderRadius: 'var(--r-xs)',
                  transition: 'width 600ms cubic-bezier(0.2,0,0,1), opacity var(--transition)',
                  backgroundImage: blockTone
                    ? 'repeating-linear-gradient(135deg, transparent, transparent 5px, rgba(201,146,63,0.22) 5px, rgba(201,146,63,0.22) 7px)'
                    : 'none',
                }}
              />
            </div>
            <span
              className="tnum"
              style={{ flex: '0 0 52px', fontSize: 'var(--fs-xs)', fontFamily: 'var(--font-mono)', color: 'var(--text-primary)', fontWeight: 600, textAlign: 'right' }}
            >
              {valueFmt(v)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function ChartLegend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 14px', marginTop: 4 }}>
      {items.map((it) => (
        <span key={it.label} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 'var(--fs-xs)', color: 'var(--text-muted)' }}>
          <span style={{ width: 9, height: 9, borderRadius: 2, background: it.color }} />
          {it.label}
        </span>
      ))}
    </div>
  );
}
