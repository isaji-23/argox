// Search input with leading icon and clear button.
import { Icon } from '../shared/Icon';

interface SearchInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  width?: number | string;
}

export function SearchInput({ value, onChange, placeholder = 'Search…', width }: SearchInputProps) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        width,
        padding: '6px 11px',
        background: 'var(--bg-surface-3)',
        border: '1px solid var(--border-strong)',
        borderRadius: 'var(--r-md)',
      }}
    >
      <Icon name="search" size={14} style={{ color: 'var(--text-muted)' }} />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          flex: 1,
          minWidth: 0,
          background: 'transparent',
          border: 'none',
          outline: 'none',
          color: 'var(--text-primary)',
          fontSize: 'var(--fs-sm)',
        }}
      />
      {value && (
        <button
          type="button"
          onClick={() => onChange('')}
          style={{ background: 'none', border: 'none', color: 'var(--text-muted)', display: 'flex', padding: 0 }}
        >
          <Icon name="x" size={13} />
        </button>
      )}
    </div>
  );
}
