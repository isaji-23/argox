import { cn } from '../../lib/utils';
import { Icon } from '../shared/Icon';

interface SearchInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  width?: string | number;
  className?: string;
}

export function SearchInput({
  value,
  onChange,
  placeholder = 'Search…',
  width,
  className
}: SearchInputProps) {
  return (
    <div
      className={cn(
        "flex items-center gap-2 px-3 py-1.5 bg-surface-3 border border-border-strong rounded-md transition-colors focus-within:border-accent-border",
        className
      )}
      style={{ width }}
    >
      <Icon name="search" size={14} className="text-text-muted" />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="flex-1 min-w-0 bg-transparent border-none outline-none text-text-primary text-sm placeholder:text-text-faint"
      />
      {value && (
        <button
          onClick={() => onChange('')}
          className="bg-none border-none text-text-muted flex p-0 hover:text-text-primary transition-colors"
        >
          <Icon name="x" size={13} />
        </button>
      )}
    </div>
  );
}
