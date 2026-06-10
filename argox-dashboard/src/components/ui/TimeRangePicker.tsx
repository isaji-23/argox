import { useState, useRef, useEffect } from 'react';
import { cn } from '../../lib/utils';
import { Icon } from '../shared/Icon';

export const TIME_RANGES = [
  { value: '1h',  label: 'Last 1 hour' },
  { value: '24h', label: 'Last 24 hours' },
  { value: '7d',  label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
];

interface TimeRangePickerProps {
  value: string;
  onChange: (value: string) => void;
}

export function TimeRangePicker({ value, onChange }: TimeRangePickerProps) {
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

  const currentRange = TIME_RANGES.find((t) => t.value === value) || TIME_RANGES[0];

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-text-primary bg-surface-3 border border-border-strong rounded-md transition-colors"
      >
        <Icon name="clock" size={14} className="text-text-muted" />
        {currentRange.label}
        <Icon name="chevronDown" size={13} className="text-text-muted" />
      </button>

      {open && (
        <div className="absolute top-[calc(100%+5px)] right-0 z-50 w-[240px] bg-overlay border border-border-strong rounded-md shadow-pop p-1.5 ax-fade-in">
          <div className="px-2 pt-1 pb-2 text-2xs font-bold tracking-widest uppercase text-text-faint">
            Quick ranges
          </div>
          {TIME_RANGES.map((t) => {
            const isSelected = t.value === value;
            return (
              <button
                key={t.value}
                onClick={() => {
                  onChange(t.value);
                  setOpen(false);
                }}
                className={cn(
                  "flex items-center justify-between w-full px-2 py-1.5 text-sm text-left rounded-sm transition-colors",
                  isSelected
                    ? "text-text-primary bg-accent-surface"
                    : "text-text-secondary bg-transparent hover:bg-surface-3 hover:text-text-primary"
                )}
              >
                {t.label}
                {isSelected && <Icon name="check" size={14} className="text-accent" />}
              </button>
            );
          })}
          <div className="border-t border-border mt-1.5 pt-2 flex items-center gap-2 px-2 pb-1">
            <Icon name="clock" size={13} className="text-text-faint" />
            <span className="text-xs text-text-muted">UTC · auto-refresh 30s</span>
          </div>
        </div>
      )}
    </div>
  );
}
