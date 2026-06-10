import React from 'react';
import { cn } from '../../lib/utils';

export interface BadgeProps {
  children: React.ReactNode;
  tone?: 'neutral' | 'accent' | 'gold' | 'allow' | 'warn' | 'block' | 'error';
  mono?: boolean;
  className?: string;
}

const TONES = {
  neutral: "text-text-secondary bg-surface-3 border-border",
  accent:  "text-accent bg-accent-surface border-accent-border",
  gold:    "text-gold-bright bg-gold-surface border-gold-border",
  allow:   "text-allow bg-allow-surface border-allow-border",
  warn:    "text-warn bg-warn-surface border-warn-border",
  block:   "text-block-bright bg-block-bg border-block-border",
  error:   "text-block-bright bg-block-surface border-block-border",
};

export function Badge({ children, tone = 'neutral', mono, className }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-0.5 text-xs font-semibold border rounded-sm transition-all whitespace-nowrap leading-tight",
        TONES[tone],
        mono && "font-mono",
        className
      )}
    >
      {children}
    </span>
  );
}

export function StatusDot({ status }: { status: 'ok' | 'error' | 'warn' | string }) {
  const color = status === 'ok' ? 'bg-allow' : status === 'error' ? 'bg-block' : 'bg-warn';
  const shadowColor = status === 'ok' ? 'var(--allow-surface)' : status === 'error' ? 'var(--block-surface)' : 'var(--warn-surface)';

  return (
    <span
      className={cn("w-1.5 h-1.5 rounded-full flex-shrink-0", color)}
      style={{ boxShadow: `0 0 0 3px ${shadowColor}` }}
    />
  );
}
