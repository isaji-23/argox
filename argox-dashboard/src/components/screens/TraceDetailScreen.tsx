// Trace detail: summary header, KPI strip, AI-Act evidence banner, span
// waterfall, selected-span inspector, and the run record.
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useShell } from '../../App';
import { api, APIError, type SpanDetail, type TraceDetailResponse, type RunDetail } from '../../lib/api';
import { fmtMs, fmtUsd, fmtNum, fmtCompact } from '../../lib/utils';
import { Icon, type IconName } from '../shared/Icon';
import { Button } from '../ui/Button';
import { Badge, DecisionBadge, StatusDot } from '../ui/Badge';
import { Panel, PanelHeader } from '../ui/Panel';
import { Skeleton, ErrorState, EmptyState } from '../ui/States';
import { Waterfall } from './Waterfall';
import { RunRecord } from './RunRecord';
import { SPAN_META, deriveSpanType } from '../shared/spanMeta';
import { useToast } from '../ui/Toast';

function Meta({ icon, v }: { icon: IconName; v: ReactNode }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
      <Icon name={icon} size={13} style={{ color: 'var(--text-faint)' }} />
      <span style={{ color: 'var(--text-secondary)' }}>{v}</span>
    </span>
  );
}

function Kpi({ label, value, icon, tone }: { label: string; value: ReactNode; icon: IconName; tone?: 'block' }) {
  const blocked = tone === 'block';
  return (
    <div
      style={{
        padding: '11px 14px',
        borderRadius: 'var(--r-md)',
        background: blocked ? 'var(--block-bg)' : 'var(--bg-surface)',
        border: '1px solid ' + (blocked ? 'var(--block-border)' : 'var(--border)'),
        borderLeft: blocked ? '2.5px solid var(--block-edge)' : '1px solid var(--border)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 5, color: blocked ? 'var(--block-bright)' : 'var(--text-muted)' }}>
        <Icon name={icon} size={13} />
        <span style={{ fontSize: 'var(--fs-2xs)', fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase' }}>{label}</span>
      </div>
      <div className="tnum" style={{ fontSize: 'var(--fs-xl)', fontWeight: 600, fontFamily: 'var(--font-display)', color: blocked ? 'var(--block-ink)' : 'var(--text-primary)', letterSpacing: '-0.01em' }}>
        {value}
      </div>
    </div>
  );
}

function SelectedSpanPanel({ span }: { span: SpanDetail | null }) {
  if (!span) {
    return (
      <Panel>
        <PanelHeader title="Span detail" icon="layers" />
        <div style={{ marginTop: 12, fontSize: 'var(--fs-sm)', color: 'var(--text-muted)' }}>Select a span in the waterfall to inspect its attributes.</div>
      </Panel>
    );
  }
  const type = deriveSpanType(span.name, span.attributes, !!span.parent_span_id);
  const attrs = Object.entries(span.attributes ?? {});
  return (
    <Panel>
      <PanelHeader
        title={<span style={{ fontFamily: 'var(--font-mono)' }}>{span.name}</span>}
        icon={SPAN_META[type].icon}
        right={span.policy_decision ? <DecisionBadge decision={span.policy_decision} size="sm" /> : <Badge tone="neutral">{SPAN_META[type].label}</Badge>}
      />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 14 }}>
        <Field label="Span ID" value={span.span_id} />
        <Field label="Parent" value={span.parent_span_id ?? '—'} />
        <Field label="Duration" value={fmtMs(span.duration_ms)} />
        <Field label="Start" value={new Date(span.start_time).toLocaleTimeString('en-US', { hour12: false })} />
      </div>
      {attrs.length > 0 && (
        <div style={{ marginTop: 14, border: '1px solid var(--border)', borderRadius: 'var(--r-md)', overflow: 'hidden' }}>
          {attrs.map(([k, v], i) => (
            <div
              key={k}
              style={{
                display: 'grid',
                gridTemplateColumns: '0.8fr 1.2fr',
                gap: 10,
                padding: '7px 11px',
                borderBottom: i < attrs.length - 1 ? '1px solid var(--border-faint)' : 'none',
                fontFamily: 'var(--font-mono)',
                fontSize: 'var(--fs-xs)',
              }}
            >
              <span style={{ color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis' }}>{k}</span>
              <span style={{ color: 'var(--text-primary)', wordBreak: 'break-word' }}>{String(v)}</span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ padding: '8px 11px', borderRadius: 'var(--r-sm)', background: 'var(--bg-surface-2)', border: '1px solid var(--border)' }}>
      <div style={{ fontSize: 'var(--fs-2xs)', color: 'var(--text-faint)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 'var(--fs-xs)', fontFamily: 'var(--font-mono)', color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</div>
    </div>
  );
}

export function TraceDetailScreen() {
  const { traceId } = useParams();
  const navigate = useNavigate();
  const { reloadKey } = useShell();
  const toast = useToast();

  const [trace, setTrace] = useState<TraceDetailResponse | null>(null);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!traceId) return;
    setLoading(true);
    setError(null);
    setNotFound(false);
    // Run record may legitimately be absent (404) — swallow that to null.
    Promise.all([
      api.getTrace(traceId),
      api.getRunByTrace(traceId).catch((e) => {
        if (e instanceof APIError && e.status === 404) return null;
        throw e;
      }),
    ])
      .then(([t, r]) => {
        setTrace(t);
        setRun(r);
        setSelected(t.spans[0]?.span_id ?? null);
      })
      .catch((e) => {
        if (e instanceof APIError && e.status === 404) setNotFound(true);
        else setError(e instanceof Error ? e.message : 'Failed to load trace');
      })
      .finally(() => setLoading(false));
  }, [traceId]);

  useEffect(() => {
    load();
  }, [load, reloadKey]);

  const spans = useMemo(() => trace?.spans ?? [], [trace]);
  const traceStartMs = useMemo(() => (spans.length ? Math.min(...spans.map((s) => new Date(s.start_time).getTime())) : 0), [spans]);
  const totalMs = useMemo(() => {
    if (trace?.duration_ms) return trace.duration_ms;
    if (!spans.length) return 1;
    const end = Math.max(...spans.map((s) => new Date(s.end_time).getTime()));
    return Math.max(end - traceStartMs, 1);
  }, [trace, spans, traceStartMs]);

  const blockedCount = spans.filter((s) => s.policy_decision === 'block').length;
  const decision = blockedCount > 0 ? 'block' : spans.some((s) => s.policy_decision === 'warn') ? 'warn' : 'allow';
  const status = spans.some((s) => s.run_success === false) ? 'error' : 'ok';
  const selectedSpan = spans.find((s) => s.span_id === selected) ?? null;
  const tokens = run?.tokens;

  if (!traceId) {
    return (
      <div style={{ padding: '40px 22px', maxWidth: 1320, margin: '0 auto' }}>
        <EmptyState icon="traces" title="No trace selected" body="Open a trace from the list to see its waterfall." />
      </div>
    );
  }

  if (notFound) {
    return (
      <div style={{ padding: '40px 22px', maxWidth: 1320, margin: '0 auto' }}>
        <Panel>
          <EmptyState icon="traces" title="Trace not found" body={`No trace with id ${traceId}.`} action={<Button variant="secondary" icon="chevronLeft" onClick={() => navigate('/traces')}>Back to traces</Button>} />
        </Panel>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: '40px 22px', maxWidth: 1320, margin: '0 auto' }}>
        <Panel>
          <ErrorState title="Failed to load trace" body={error} onRetry={load} />
        </Panel>
      </div>
    );
  }

  if (loading || !trace) {
    return (
      <div style={{ padding: '18px 22px', maxWidth: 1320, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Skeleton w="40%" h={24} />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} h={64} r={8} />)}
        </div>
        <Skeleton h={280} r={10} />
      </div>
    );
  }

  return (
    <div className="ax-fade-in" style={{ padding: '18px 22px 40px', maxWidth: 1320, margin: '0 auto' }}>
      {/* Trace summary header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, marginBottom: 14 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 11, marginBottom: 6 }}>
            <StatusDot status={status} />
            <h1 style={{ margin: 0, fontSize: 'var(--fs-xl)', fontWeight: 600, letterSpacing: '-0.015em', fontFamily: 'var(--font-mono)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 520 }}>
              {trace.trace_id}
            </h1>
            <DecisionBadge decision={decision} />
            {trace.truncated && <Badge tone="warn">truncated</Badge>}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap', fontSize: 'var(--fs-sm)', color: 'var(--text-muted)' }}>
            <Meta icon="layers" v={`${spans.length} spans`} />
            <Meta icon="gauge" v={fmtMs(totalMs)} />
            {run?.agent_name && <Meta icon="bolt" v={run.agent_name} />}
            {run?.timestamp && <Meta icon="clock" v={new Date(run.timestamp).toLocaleString('en-US', { hour12: false }) + ' UTC'} />}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, flex: '0 0 auto' }}>
          <Button variant="secondary" size="sm" icon="copy" onClick={() => { navigator.clipboard?.writeText(trace.trace_id); toast.success('Trace ID copied'); }}>
            Copy ID
          </Button>
          <Button variant="secondary" size="sm" icon="chevronLeft" onClick={() => navigate('/traces')}>
            Back
          </Button>
        </div>
      </div>

      {/* KPI strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 14 }}>
        <Kpi label="Spans" value={spans.length} icon="layers" />
        <Kpi label="Tokens (in / out)" value={`${fmtCompact(tokens?.input ?? 0)} / ${fmtCompact(tokens?.output ?? 0)}`} icon="hash" />
        <Kpi label="Cost" value={run?.cost_usd != null ? fmtUsd(run.cost_usd) : '—'} icon="dollar" />
        <Kpi label="Policy blocks" value={blockedCount} icon="ban" tone="block" />
      </div>

      {/* AI Act evidence banner */}
      {blockedCount > 0 && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 13,
            padding: '11px 15px',
            marginBottom: 16,
            background: 'var(--block-bg)',
            border: '1px solid var(--block-border)',
            borderLeft: '3px solid var(--block-edge)',
            borderRadius: 'var(--r-md)',
          }}
        >
          <span style={{ width: 30, height: 30, borderRadius: 'var(--r-sm)', display: 'grid', placeItems: 'center', background: 'var(--block-surface)', color: 'var(--block-bright)', flex: '0 0 auto' }}>
            <Icon name="shieldAlert" size={17} />
          </span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 'var(--fs-sm)', fontWeight: 600, color: 'var(--block-ink)' }}>
              {fmtNum(blockedCount)} {blockedCount === 1 ? 'action' : 'actions'} blocked by policy · enforcement evidence recorded
            </div>
            <div style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-secondary)', marginTop: 1 }}>
              Audit span emitted for EU AI Act Art. 13 traceability.
            </div>
          </div>
        </div>
      )}

      {/* Waterfall + legend */}
      <div style={{ marginBottom: 18 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 9 }}>
          <h2 style={{ margin: 0, fontSize: 'var(--fs-md)', fontWeight: 600 }}>Span waterfall</h2>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginLeft: 4 }}>
            {(['llm', 'tool', 'processor'] as const).map((t) => (
              <span key={t} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 'var(--fs-xs)', color: 'var(--text-muted)' }}>
                <span style={{ width: 9, height: 9, borderRadius: 2, background: SPAN_META[t].color }} />
                {SPAN_META[t].label}
              </span>
            ))}
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 'var(--fs-xs)', color: 'var(--block-bright)', fontWeight: 550 }}>
              <span style={{ width: 9, height: 9, borderRadius: 2, background: 'var(--block)', border: '1px solid var(--block-edge)' }} />
              Blocked
            </span>
          </div>
        </div>
        {spans.length === 0 ? (
          <Panel>
            <EmptyState icon="layers" title="No spans in this trace" />
          </Panel>
        ) : (
          <Waterfall spans={spans} traceStartMs={traceStartMs} totalMs={totalMs} selected={selected} onSelect={setSelected} />
        )}
      </div>

      {/* Selected span + run record */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <SelectedSpanPanel span={selectedSpan} />
        <RunRecord run={run} />
      </div>
    </div>
  );
}
