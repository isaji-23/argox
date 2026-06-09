import { useState, useRef, useEffect } from 'react';
import { cn } from '../../lib/utils';
import { Icon } from '../shared/Icon';

interface Option {
  value: string;
  label: string;
}

interface SelectProps {
  value: string;
  options: (Option | string)[];
  onChange: (value: string) => void;
  icon?: string;
  minWidth?: number;
  size?: 'sm' | 'md';
  className?: string;
}

export function Select({
  value,
  options,
  onChange,
  icon,
  minWidth = 120,
  size = 'md',
  className
}: SelectProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleOutsideClick);
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, []);

  const normalizedOptions = options.map(o => typeof o === 'string' ? { value: o, label: o } : o);
  const currentOption = normalizedOptions.find(o => o.value === value) || normalizedOptions[0];

  return (
    <div ref={ref} className={cn("relative", className)} style={{ minWidth }}>
      <button
        onClick={() => setOpen(!open)}
        className={cn(
          "inline-flex items-center justify-between w-full rounded-md border border-border-strong bg-surface-3 text-text-primary font-medium transition-colors",
          size === 'sm' ? "px-2 py-1.5 text-sm gap-1.5" : "px-3 py-1.5 text-sm gap-2"
        )}
      >
        <span className="inline-flex items-center gap-2 overflow-hidden">
          {icon && <Icon name={icon} size={14} className="text-text-muted" />}
          <span className="truncate">{currentOption?.label}</span>
        </span>
        <Icon name="chevronsUpDown" size={13} className="text-text-muted flex-shrink-0" />
      </button>

      {open && (
        <div className="absolute top-[calc(100%+5px)] left-0 min-w-full z-50 bg-overlay border border-border-strong rounded-md shadow-pop p-1 max-h-[280px] overflow-y-auto ax-fade-in">
          {normalizedOptions.map((o) => {
            const isSelected = o.value === value;
            return (
              <button
                key={o.value}
                onClick={() => {
                  onChange(o.value);
                  setOpen(false);
                }}
                className={cn(
                  "flex items-center justify-between gap-3 w-full px-2 py-1.5 text-sm text-left rounded-sm transition-colors whitespace-nowrap",
                  isSelected
                    ? "text-text-primary bg-accent-surface"
                    : "text-text-secondary bg-transparent hover:bg-surface-3 hover:text-text-primary"
                )}
              >
                {o.label}
                {isSelected && <Icon name="check" size={14} className="text-accent" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
