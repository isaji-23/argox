// Span waterfall: bars positioned by offset/width within the trace window.
// Blocked spans get the bronze-edge + hatch + glow treatment.
import { useMemo } from 'react';
import type { SpanDetail } from '../../lib/api';
import { fmtMs } from '../../lib/utils';
import { Icon } from '../shared/Icon';
import { Badge } from '../ui/Badge';
import { SPAN_META, deriveSpanType } from '../shared/spanMeta';

const ROW_H = 30;
const BAR_H = 13;
const NAME_W = 308;

function ruleOf(attrs: Record<string, unknown>): string | null {
  for (const k of ['policy.rule_id', 'policy.rule', 'rule_id', 'argox.policy.rule']) {
    const v = attrs[k];
    if (typeof v === 'string' && v) return v;
  }
  return null;
}

interface WaterfallProps {
  spans: SpanDetail[];
  traceStartMs: number;
  totalMs: number;
  selected: string | null;
  onSelect: (id: string) => void;
}

export function Waterfall({ spans, traceStartMs, totalMs, selected, onSelect }: WaterfallProps) {
  const byId = useMemo(() => Object.fromEntries(spans.map((s) => [s.span_id, s])), [spans]);
  const depthOf = (s: SpanDetail) => {
    let d = 0;
    let p = s.parent_span_id;
    while (p && byId[p]) {
      d++;
      p = byId[p].parent_span_id;
    }
    return d;
  };

  const total = Math.max(totalMs, 1);
  const tickStep = total > 4000 ? 1000 : total > 1500 ? 500 : 250;
  const ticks: number[] = [];
  for (let t = 0; t <= total; t += tickStep) ticks.push(t);

  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', overflow: 'hidden', background: 'var(--bg-surface)' }}>
      {/* axis header */}
      <div style={{ display: 'flex', alignItems: 'stretch', borderBottom: '1px solid var(--border)', background: 'var(--bg-surface-2)' }}>
        <div
          style={{
            width: NAME_W,
            flex: `0 0 ${NAME_W}px`,
            padding: '7px 14px',
            borderRight: '1px solid var(--border)',
            fontSize: 'var(--fs-2xs)',
            fontWeight: 600,
            letterSpacing: '0.07em',
            textTransform: 'uppercase',
            color: 'var(--text-faint)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <span>Span</span>
          <span>{spans.length} spans</span>
        </div>
        <div style={{ flex: 1, position: 'relative', height: 30 }}>
          {ticks.map((t) => (
            <div key={t} style={{ position: 'absolute', left: `${(t / total) * 100}%`, top: 0, bottom: 0, borderLeft: t === 0 ? 'none' : '1px solid var(--chart-grid)' }}>
              <span style={{ position: 'absolute', left: 5, top: 7, fontSize: 'var(--fs-2xs)', color: 'var(--text-faint)', fontFamily: 'var(--font-mono)' }}>
                {t === 0 ? '0ms' : fmtMs(t)}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* rows */}
      <div>
        {spans.map((s) => {
          const type = deriveSpanType(s.name, s.attributes, !!s.parent_span_id);
          const meta = SPAN_META[type];
          const depth = depthOf(s);
          const blocked = s.policy_decision === 'block';
          const warned = s.policy_decision === 'warn';
          const sel = selected === s.span_id;
          const startMs = new Date(s.start_time).getTime() - traceStartMs;
          const leftPct = Math.max((startMs / total) * 100, 0);
          const widthPct = Math.max((s.duration_ms / total) * 100, 0.6);
          const barColor = blocked ? 'var(--block)' : meta.color;
          const rule = blocked ? ruleOf(s.attributes) : null;
          return (
            <div
              key={s.span_id}
              onClick={() => onSelect(s.span_id)}
              style={{
                display: 'flex',
                alignItems: 'stretch',
                cursor: 'pointer',
                position: 'relative',
                minHeight: ROW_H,
                borderBottom: '1px solid var(--border-faint)',
                background: blocked ? 'var(--block-bg)' : sel ? 'var(--accent-surface)' : 'transparent',
                borderLeft: blocked ? '2.5px solid var(--block-edge)' : '2.5px solid transparent',
                transition: 'background var(--transition)',
              }}
              onMouseEnter={(e) => {
                if (!blocked && !sel) e.currentTarget.style.background = 'var(--bg-surface-2)';
              }}
              onMouseLeave={(e) => {
                if (!blocked && !sel) e.currentTarget.style.background = 'transparent';
              }}
            >
              {/* name col */}
              <div
                style={{
                  width: NAME_W,
                  flex: `0 0 ${NAME_W}px`,
                  padding: '0 14px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  borderRight: '1px solid var(--border)',
                  paddingLeft: 14 + depth * 15,
                }}
              >
                <span style={{ color: blocked ? 'var(--block-bright)' : meta.color, display: 'flex', flex: '0 0 auto' }}>
                  <Icon name={blocked ? 'ban' : meta.icon} size={13} strokeWidth={blocked ? 2 : 1.7} />
                </span>
                <span
                  style={{
                    fontSize: 'var(--fs-sm)',
                    fontWeight: blocked ? 600 : 480,
                    color: blocked ? 'var(--block-ink)' : 'var(--text-primary)',
                    fontFamily: 'var(--font-mono)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {s.name}
                </span>
                {rule && (
                  <Badge tone="block" mono style={{ marginLeft: 'auto', flex: '0 0 auto', padding: '1px 5px', fontSize: 'var(--fs-2xs)' }}>
                    {rule}
                  </Badge>
                )}
                {warned && !blocked && (
                  <span style={{ marginLeft: 'auto', color: 'var(--warn)', display: 'flex' }}>
                    <Icon name="warn" size={12} />
                  </span>
                )}
              </div>
              {/* timeline col */}
              <div style={{ flex: 1, position: 'relative', display: 'flex', alignItems: 'center' }}>
                {ticks.map((t) => (t > 0 ? <div key={t} style={{ position: 'absolute', left: `${(t / total) * 100}%`, top: 0, bottom: 0, borderLeft: '1px solid var(--grid-line)' }} /> : null))}
                <div
                  style={{
                    position: 'absolute',
                    left: `${leftPct}%`,
                    width: `${widthPct}%`,
                    height: BAR_H,
                    borderRadius: 3,
                    minWidth: 3,
                    background: barColor,
                    border: blocked ? '1px solid var(--block-edge)' : 'none',
                    boxShadow: blocked
                      ? '0 0 0 1px var(--block-border), 0 0 14px var(--block-glow)'
                      : sel
                        ? `0 0 0 1px ${barColor}`
                        : 'none',
                    display: 'flex',
                    alignItems: 'center',
                    backgroundImage: blocked
                      ? 'repeating-linear-gradient(135deg, transparent, transparent 4px, rgba(201,146,63,0.28) 4px, rgba(201,146,63,0.28) 6px)'
                      : 'none',
                  }}
                >
                  <span
                    style={{
                      position: 'absolute',
                      left: 'calc(100% + 7px)',
                      fontSize: 'var(--fs-2xs)',
                      color: blocked ? 'var(--block-bright)' : 'var(--text-muted)',
                      fontFamily: 'var(--font-mono)',
                      whiteSpace: 'nowrap',
                      fontWeight: blocked ? 600 : 400,
                    }}
                  >
                    {fmtMs(s.duration_ms)}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
