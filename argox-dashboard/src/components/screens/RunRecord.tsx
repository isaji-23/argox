// Run-record panel: prompt/output, tool calls, token usage, policy violations.
// Degrades to a hint when no run record was captured.
import { useState } from 'react';
import type { RunDetail } from '../../lib/api';
import { fmtNum, fmtUsd, fmtMs } from '../../lib/utils';
import { Icon } from '../shared/Icon';
import { Badge } from '../ui/Badge';
import { Panel, PanelHeader, SectionLabel } from '../ui/Panel';
import { useToast } from '../ui/Toast';

function ContentBlock({ label, sublabel, text, defaultOpen = true }: { label: string; sublabel?: string; text: string; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const [copied, setCopied] = useState(false);
  const toast = useToast();
  const copy = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard?.writeText(text).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1200);
        toast.success(`${label} copied`);
      },
      () => toast.error('Clipboard unavailable'),
    );
  };
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--r-md)', overflow: 'hidden', background: 'var(--bg-base)' }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 9,
          width: '100%',
          padding: '8px 12px',
          background: 'var(--bg-surface-2)',
          border: 'none',
          borderBottom: open ? '1px solid var(--border)' : 'none',
        }}
      >
        <Icon name={open ? 'chevronDown' : 'chevronRight'} size={14} style={{ color: 'var(--text-muted)' }} />
        <span style={{ fontSize: 'var(--fs-sm)', fontWeight: 600, color: 'var(--text-primary)' }}>{label}</span>
        <Badge tone="gold" style={{ fontSize: 'var(--fs-2xs)', padding: '1px 6px' }}>
          <Icon name="user" size={10} /> user content · PII redacted
        </Badge>
        <span style={{ flex: 1 }} />
        {sublabel && <span style={{ fontSize: 'var(--fs-2xs)', color: 'var(--text-faint)', fontFamily: 'var(--font-mono)' }}>{sublabel}</span>}
        <span onClick={copy} style={{ display: 'inline-flex', color: copied ? 'var(--allow)' : 'var(--text-muted)' }}>
          <Icon name={copied ? 'check' : 'copy'} size={14} />
        </span>
      </button>
      {open && (
        <pre
          style={{
            margin: 0,
            padding: '12px 14px',
            fontSize: 'var(--fs-sm)',
            fontFamily: 'var(--font-mono)',
            lineHeight: 1.6,
            color: 'var(--text-secondary)',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            maxHeight: 240,
            overflowY: 'auto',
          }}
        >
          {text || '—'}
        </pre>
      )}
    </div>
  );
}

export function RunRecord({ run }: { run: RunDetail | null }) {
  if (!run) {
    return (
      <Panel>
        <PanelHeader title="Run record" icon="database" />
        <div
          style={{
            marginTop: 14,
            padding: '16px',
            borderRadius: 'var(--r-md)',
            background: 'var(--bg-surface-2)',
            border: '1px dashed var(--border-strong)',
            display: 'flex',
            alignItems: 'center',
            gap: 12,
          }}
        >
          <span style={{ color: 'var(--text-muted)' }}>
            <Icon name="database" size={18} />
          </span>
          <div>
            <div style={{ fontSize: 'var(--fs-sm)', fontWeight: 600, color: 'var(--text-primary)' }}>No run record available</div>
            <div style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-muted)', marginTop: 2 }}>
              Wire <code style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent)' }}>HttpRunExporter</code> to capture prompts, outputs and tool results for this agent.
            </div>
          </div>
        </div>
      </Panel>
    );
  }

  const called = run.tools?.called ?? [];
  const byCall = run.tokens?.by_api_call ?? [];
  const violations = run.policies?.violations ?? [];
  const tIn = run.tokens?.input ?? byCall.reduce((s, c) => s + (c.input ?? 0), 0);
  const tOut = run.tokens?.output ?? byCall.reduce((s, c) => s + (c.output ?? 0), 0);

  return (
    <Panel>
      <PanelHeader
        title="Run record"
        subtitle="Prompt, output, tool & token detail · captured by HttpRunExporter"
        icon="database"
        right={
          <Badge tone="neutral" mono>
            {byCall.length} LLM · {called.length} tools
          </Badge>
        }
      />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 16 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <ContentBlock label="Prompt" sublabel={`${fmtNum(tIn)} tok in`} text={run.prompt ?? ''} />
          <ContentBlock label="Final output" sublabel={`${fmtNum(tOut)} tok out`} text={run.final_output ?? ''} />
        </div>

        {/* Tool calls */}
        {called.length > 0 && (
          <div>
            <SectionLabel icon="tool" color="var(--span-tool)">
              Tool calls
            </SectionLabel>
            <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--r-md)', overflow: 'hidden' }}>
              {called.map((tc, i) => (
                <div
                  key={i}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 12,
                    padding: '9px 13px',
                    borderBottom: i < called.length - 1 ? '1px solid var(--border-faint)' : 'none',
                    background: tc.blocked ? 'var(--block-bg)' : 'transparent',
                    borderLeft: tc.blocked ? '2.5px solid var(--block-edge)' : '2.5px solid transparent',
                  }}
                >
                  <span style={{ color: tc.blocked ? 'var(--block-bright)' : 'var(--span-tool)', display: 'flex' }}>
                    <Icon name={tc.blocked ? 'ban' : 'tool'} size={14} strokeWidth={tc.blocked ? 2 : 1.7} />
                  </span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-sm)', fontWeight: 550, color: tc.blocked ? 'var(--block-ink)' : 'var(--text-primary)', flex: '0 0 160px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {tc.name}
                  </span>
                  <span className="tnum" style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-xs)', color: 'var(--text-muted)', flex: '0 0 56px' }}>
                    {tc.duration != null ? fmtMs(tc.duration) : '—'}
                  </span>
                  {tc.blocked && tc.block_reason ? (
                    <Badge tone="block" mono style={{ flex: '0 0 auto' }}>
                      {tc.block_reason}
                    </Badge>
                  ) : (
                    <span style={{ flex: '0 0 auto', width: 6 }} />
                  )}
                  <span
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: 'var(--fs-xs)',
                      color: tc.blocked ? 'var(--block-bright)' : 'var(--text-secondary)',
                      flex: 1,
                      minWidth: 0,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      textAlign: 'right',
                      opacity: 0.92,
                    }}
                  >
                    {tc.result ?? ''}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: '0.9fr 1.1fr', gap: 14 }}>
          {/* LLM token table */}
          <div>
            <SectionLabel icon="llm" color="var(--span-llm)">
              LLM calls · tokens
            </SectionLabel>
            <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--r-md)', overflow: 'hidden' }}>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '34px 1fr 64px 64px',
                  padding: '6px 12px',
                  background: 'var(--bg-surface-2)',
                  borderBottom: '1px solid var(--border)',
                  fontSize: 'var(--fs-2xs)',
                  fontWeight: 600,
                  letterSpacing: '0.05em',
                  textTransform: 'uppercase',
                  color: 'var(--text-faint)',
                }}
              >
                <span>#</span>
                <span>Call</span>
                <span style={{ textAlign: 'right' }}>In</span>
                <span style={{ textAlign: 'right' }}>Out</span>
              </div>
              {byCall.length === 0 && (
                <div style={{ padding: '10px 12px', fontSize: 'var(--fs-xs)', color: 'var(--text-faint)', fontFamily: 'var(--font-mono)' }}>No per-call token data</div>
              )}
              {byCall.map((c) => (
                <div
                  key={c.call}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '34px 1fr 64px 64px',
                    padding: '8px 12px',
                    borderBottom: '1px solid var(--border-faint)',
                    alignItems: 'center',
                    fontFamily: 'var(--font-mono)',
                    fontSize: 'var(--fs-xs)',
                  }}
                >
                  <span style={{ color: 'var(--text-faint)' }}>{c.call}</span>
                  <span style={{ color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis' }}>call #{c.call}</span>
                  <span className="tnum" style={{ textAlign: 'right', color: 'var(--text-secondary)' }}>{fmtNum(c.input ?? 0)}</span>
                  <span className="tnum" style={{ textAlign: 'right', color: 'var(--accent)' }}>{fmtNum(c.output ?? 0)}</span>
                </div>
              ))}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '34px 1fr 64px 64px',
                  padding: '8px 12px',
                  background: 'var(--bg-surface-2)',
                  alignItems: 'center',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 'var(--fs-xs)',
                  fontWeight: 600,
                }}
              >
                <span />
                <span style={{ color: 'var(--text-muted)' }}>Total</span>
                <span className="tnum" style={{ textAlign: 'right', color: 'var(--text-primary)' }}>{fmtNum(tIn)}</span>
                <span className="tnum" style={{ textAlign: 'right', color: 'var(--accent)' }}>{fmtNum(tOut)}</span>
              </div>
            </div>
          </div>

          {/* Violations + summary */}
          <div>
            <SectionLabel icon="shieldAlert" color="var(--block-bright)">
              Policy violations
            </SectionLabel>
            {violations.length === 0 ? (
              <div style={{ padding: '12px 13px', border: '1px solid var(--border)', borderRadius: 'var(--r-md)', fontSize: 'var(--fs-xs)', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ color: 'var(--allow)', display: 'flex' }}>
                  <Icon name="check" size={14} />
                </span>
                No policy violations recorded for this run.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {violations.map((v, i) => (
                  <div
                    key={i}
                    style={{
                      borderRadius: 'var(--r-md)',
                      background: 'var(--block-bg)',
                      border: '1px solid var(--block-border)',
                      borderLeft: '2.5px solid var(--block-edge)',
                      padding: '8px 11px',
                      fontSize: 'var(--fs-xs)',
                      lineHeight: 1.55,
                      color: 'var(--block-ink)',
                      fontFamily: 'var(--font-mono)',
                    }}
                  >
                    {v}
                  </div>
                ))}
              </div>
            )}

            <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <Summary label="Model" value={run.model ?? '—'} mono />
              <Summary label="Cost" value={run.cost_usd != null ? fmtUsd(run.cost_usd) : '—'} />
              <Summary label="Duration" value={run.duration_seconds != null ? run.duration_seconds.toFixed(2) + 's' : '—'} />
              <Summary label="Success" value={run.success == null ? '—' : run.success ? 'yes' : 'no'} tone={run.success === false ? 'block' : undefined} />
            </div>
          </div>
        </div>
      </div>
    </Panel>
  );
}

function Summary({ label, value, mono, tone }: { label: string; value: string; mono?: boolean; tone?: 'block' }) {
  return (
    <div style={{ padding: '8px 11px', borderRadius: 'var(--r-sm)', background: 'var(--bg-surface-2)', border: '1px solid var(--border)' }}>
      <div style={{ fontSize: 'var(--fs-2xs)', color: 'var(--text-faint)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>{label}</div>
      <div
        style={{
          fontSize: 'var(--fs-sm)',
          fontWeight: 600,
          color: tone === 'block' ? 'var(--block-bright)' : 'var(--text-primary)',
          fontFamily: mono ? 'var(--font-mono)' : 'var(--font-ui)',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {value}
      </div>
    </div>
  );
}
