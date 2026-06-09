import { cn } from '../../lib/utils';
import { Icon } from '../shared/Icon';

export type Decision = 'allow' | 'warn' | 'block';

interface DecisionConfig {
  label: string;
  icon: string;
  color: string;
  bg: string;
  border: string;
  edge?: boolean;
}

const DECISION_MAP: Record<Decision, DecisionConfig> = {
  allow: { label: 'Allow', icon: 'check', color: 'text-allow', bg: 'bg-allow-surface', border: 'border-allow-border' },
  warn:  { label: 'Warn',  icon: 'warn',  color: 'text-warn',  bg: 'bg-warn-surface',  border: 'border-warn-border' },
  block: { label: 'Block', icon: 'ban',   color: 'text-block-bright', bg: 'bg-block-bg', border: 'border-block-border', edge: true },
};

interface DecisionBadgeProps {
  decision: Decision;
  size?: 'sm' | 'md';
  className?: string;
}

export function DecisionBadge({ decision, size = 'md', className }: DecisionBadgeProps) {
  const config = DECISION_MAP[decision] || DECISION_MAP.allow;
  const isSm = size === 'sm';

  return (
    <span
      className={cn(
        "inline-flex items-center font-bold tracking-wide rounded-sm border transition-all whitespace-nowrap leading-none",
        isSm ? "gap-1 px-1.5 py-0.5 text-2xs" : "gap-1.5 px-2 py-1 text-xs",
        config.color,
        config.bg,
        config.border,
        config.edge ? "border-l-[2.5px] border-l-block-edge" : "border-l",
        className
      )}
    >
      <Icon name={config.icon} size={isSm ? 11 : 12} strokeWidth={2} />
      {config.label}
    </span>
  );
}
