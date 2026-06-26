// Badge / DecisionBadge / StatusDot — the policy-decision signal lives here.
import type { CSSProperties, ReactNode } from 'react';
import { Icon, type IconName } from '../shared/Icon';

type BadgeTone = 'neutral' | 'accent' | 'gold' | 'allow' | 'warn' | 'block' | 'error';

interface BadgeProps {
  children: ReactNode;
  tone?: BadgeTone;
  mono?: boolean;
  style?: CSSProperties;
}

export function Badge({ children, tone = 'neutral', mono, style }: BadgeProps) {
  const tones: Record<BadgeTone, { c: string; bg: string; b: string }> = {
    neutral: { c: 'var(--text-secondary)', bg: 'var(--bg-surface-3)', b: 'var(--border)' },
    accent: { c: 'var(--accent)', bg: 'var(--accent-surface)', b: 'var(--accent-border)' },
    gold: { c: 'var(--gold-bright)', bg: 'var(--gold-surface)', b: 'var(--gold-border)' },
    allow: { c: 'var(--allow)', bg: 'var(--allow-surface)', b: 'var(--allow-border)' },
    warn: { c: 'var(--warn)', bg: 'var(--warn-surface)', b: 'var(--warn-border)' },
    block: { c: 'var(--block-bright)', bg: 'var(--block-bg)', b: 'var(--block-border)' },
    error: { c: 'var(--block-bright)', bg: 'var(--block-surface)', b: 'var(--block-border)' },
  };
  const t = tones[tone] ?? tones.neutral;
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        padding: '2px 7px',
        fontSize: 'var(--fs-xs)',
        fontWeight: 550,
        color: t.c,
        background: t.bg,
        border: '1px solid ' + t.b,
        borderRadius: 'var(--r-sm)',
        lineHeight: 1.4,
        fontFamily: mono ? 'var(--font-mono)' : 'var(--font-ui)',
        whiteSpace: 'nowrap',
        ...style,
      }}
    >
      {children}
    </span>
  );
}

export type Decision = 'allow' | 'warn' | 'block';

interface DecisionBadgeProps {
  decision: Decision | string;
  size?: 'sm' | 'md';
}

/** The consistent policy-enforcement signal: block carries the bronze left edge. */
export function DecisionBadge({ decision, size = 'md' }: DecisionBadgeProps) {
  const map: Record<Decision, { label: string; icon: IconName; color: string; bg: string; border: string; edge?: boolean }> = {
    allow: { label: 'Allow', icon: 'check', color: 'var(--allow)', bg: 'var(--allow-surface)', border: 'var(--allow-border)' },
    warn: { label: 'Warn', icon: 'warn', color: 'var(--warn)', bg: 'var(--warn-surface)', border: 'var(--warn-border)' },
    block: { label: 'Block', icon: 'ban', color: 'var(--block-bright)', bg: 'var(--block-bg)', border: 'var(--block-border)', edge: true },
  };
  const c = map[(decision as Decision)] ?? map.allow;
  const sm = size === 'sm';
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: sm ? 4 : 5,
        padding: sm ? '2px 7px 2px 6px' : '3px 9px 3px 7px',
        fontSize: sm ? 'var(--fs-2xs)' : 'var(--fs-xs)',
        fontWeight: 600,
        fontFamily: 'var(--font-ui)',
        letterSpacing: '0.02em',
        color: c.color,
        background: c.bg,
        border: '1px solid ' + c.border,
        borderRadius: 'var(--r-sm)',
        borderLeft: c.edge ? '2.5px solid var(--block-edge)' : '1px solid ' + c.border,
        lineHeight: 1,
        whiteSpace: 'nowrap',
      }}
    >
      <Icon name={c.icon} size={sm ? 11 : 12} strokeWidth={2} />
      {c.label}
    </span>
  );
}

interface StatusDotProps {
  status: 'ok' | 'error' | 'warn' | string;
}

export function StatusDot({ status }: StatusDotProps) {
  const c = status === 'ok' ? 'var(--allow)' : status === 'error' ? 'var(--block)' : 'var(--warn)';
  return (
    <span
      style={{
        width: 7,
        height: 7,
        borderRadius: 999,
        background: c,
        boxShadow: `0 0 0 3px color-mix(in srgb, ${c} 22%, transparent)`,
        flex: '0 0 auto',
      }}
    />
  );
}
