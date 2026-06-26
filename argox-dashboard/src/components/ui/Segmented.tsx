// Segmented toggle control.
import { Icon, type IconName } from '../shared/Icon';

export interface SegmentOption {
  value: string;
  label: string;
  icon?: IconName;
  title?: string;
}

interface SegmentedProps {
  options: SegmentOption[];
  value: string;
  onChange: (value: string) => void;
  size?: 'sm' | 'md';
}

export function Segmented({ options, value, onChange, size = 'md' }: SegmentedProps) {
  return (
    <div
      style={{
        display: 'inline-flex',
        padding: 2,
        gap: 2,
        background: 'var(--bg-surface-2)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--r-md)',
      }}
    >
      {options.map((o) => {
        const sel = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            title={o.title}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: size === 'sm' ? '4px 9px' : '5px 12px',
              fontSize: size === 'sm' ? 'var(--fs-xs)' : 'var(--fs-sm)',
              fontWeight: 550,
              color: sel ? 'var(--text-primary)' : 'var(--text-muted)',
              background: sel ? 'var(--bg-surface-3)' : 'transparent',
              border: '1px solid ' + (sel ? 'var(--border-strong)' : 'transparent'),
              borderRadius: 'var(--r-sm)',
              transition: 'all var(--transition)',
              whiteSpace: 'nowrap',
            }}
          >
            {o.icon && <Icon name={o.icon} size={14} />}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
