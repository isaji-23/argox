// Panel / PanelHeader / SectionLabel — titled card surfaces.
import type { CSSProperties, ReactNode } from 'react';
import { Icon, type IconName } from '../shared/Icon';

interface PanelProps {
  children: ReactNode;
  style?: CSSProperties;
  pad?: boolean;
  className?: string;
}

export function Panel({ children, style, pad = true, className = '' }: PanelProps) {
  return (
    <div
      className={className}
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--r-lg)',
        padding: pad ? 'var(--sp-5)' : 0,
        boxShadow: 'var(--shadow-sm)',
        ...style,
      }}
    >
      {children}
    </div>
  );
}

interface PanelHeaderProps {
  title: ReactNode;
  subtitle?: ReactNode;
  icon?: IconName;
  right?: ReactNode;
}

export function PanelHeader({ title, subtitle, icon, right }: PanelHeaderProps) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 4 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 9, minWidth: 0 }}>
        {icon && (
          <span style={{ color: 'var(--text-muted)' }}>
            <Icon name={icon} size={16} />
          </span>
        )}
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 'var(--fs-md)', fontWeight: 600, color: 'var(--text-primary)', letterSpacing: '-0.01em' }}>
            {title}
          </div>
          {subtitle && <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-muted)', marginTop: 1 }}>{subtitle}</div>}
        </div>
      </div>
      {right}
    </div>
  );
}

interface SectionLabelProps {
  children: ReactNode;
  icon?: IconName;
  color?: string;
}

export function SectionLabel({ children, icon, color }: SectionLabelProps) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 8 }}>
      {icon && (
        <span style={{ color: color || 'var(--text-muted)', display: 'flex' }}>
          <Icon name={icon} size={14} />
        </span>
      )}
      <span
        style={{
          fontSize: 'var(--fs-xs)',
          fontWeight: 600,
          letterSpacing: '0.05em',
          textTransform: 'uppercase',
          color: 'var(--text-secondary)',
        }}
      >
        {children}
      </span>
    </div>
  );
}
