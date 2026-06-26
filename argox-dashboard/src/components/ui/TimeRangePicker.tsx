// Time-range quick picker (1h / 24h / 7d / 30d).
//
// Menu is portal-rendered and anchored to the trigger rect, mirroring Select,
// so it survives `overflow-hidden` ancestors.
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from '../shared/Icon';
import { TIME_RANGES, type TimeRange } from '../../lib/timeRange';

interface TimeRangePickerProps {
  value: TimeRange;
  onChange: (value: TimeRange) => void;
}

export function TimeRangePicker({ value, onChange }: TimeRangePickerProps) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const cur = TIME_RANGES.find((t) => t.value === value) ?? TIME_RANGES[1];

  useLayoutEffect(() => {
    if (open && triggerRef.current) setRect(triggerRef.current.getBoundingClientRect());
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDocDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (triggerRef.current?.contains(t) || menuRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onReflow = () => setOpen(false);
    document.addEventListener('mousedown', onDocDown);
    window.addEventListener('scroll', onReflow, true);
    window.addEventListener('resize', onReflow);
    return () => {
      document.removeEventListener('mousedown', onDocDown);
      window.removeEventListener('scroll', onReflow, true);
      window.removeEventListener('resize', onReflow);
    };
  }, [open]);

  return (
    <div style={{ position: 'relative' }}>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 8,
          padding: '6px 11px',
          fontSize: 'var(--fs-sm)',
          fontWeight: 500,
          color: 'var(--text-primary)',
          background: 'var(--bg-surface-3)',
          border: '1px solid var(--border-strong)',
          borderRadius: 'var(--r-md)',
        }}
      >
        <Icon name="clock" size={14} style={{ color: 'var(--text-muted)' }} />
        {cur.label}
        <Icon name="chevronDown" size={13} style={{ color: 'var(--text-muted)' }} />
      </button>

      {open && rect &&
        createPortal(
          <div
            ref={menuRef}
            className="ax-fade-in"
            style={{
              position: 'fixed',
              top: rect.bottom + 5,
              left: Math.max(8, rect.right - 280),
              zIndex: 1000,
              width: 280,
              background: 'var(--bg-overlay)',
              border: '1px solid var(--border-strong)',
              borderRadius: 'var(--r-md)',
              boxShadow: 'var(--shadow-pop)',
              padding: 6,
            }}
          >
            <div
              style={{
                padding: '4px 8px 7px',
                fontSize: 'var(--fs-2xs)',
                fontWeight: 600,
                letterSpacing: '0.06em',
                textTransform: 'uppercase',
                color: 'var(--text-faint)',
              }}
            >
              Quick ranges
            </div>
            {TIME_RANGES.map((t) => (
              <button
                key={t.value}
                type="button"
                onClick={() => {
                  onChange(t.value);
                  setOpen(false);
                }}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  width: '100%',
                  padding: '7px 9px',
                  fontSize: 'var(--fs-sm)',
                  textAlign: 'left',
                  color: t.value === value ? 'var(--text-primary)' : 'var(--text-secondary)',
                  background: t.value === value ? 'var(--accent-surface)' : 'transparent',
                  border: 'none',
                  borderRadius: 'var(--r-sm)',
                }}
                onMouseEnter={(e) => {
                  if (t.value !== value) e.currentTarget.style.background = 'var(--bg-surface-3)';
                }}
                onMouseLeave={(e) => {
                  if (t.value !== value) e.currentTarget.style.background = 'transparent';
                }}
              >
                {t.label}
                {t.value === value && <Icon name="check" size={14} style={{ color: 'var(--accent)' }} />}
              </button>
            ))}
            <div
              style={{
                borderTop: '1px solid var(--border)',
                marginTop: 6,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '8px 8px 4px',
              }}
            >
              <Icon name="clock" size={13} style={{ color: 'var(--text-faint)' }} />
              <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-muted)' }}>UTC · auto-refresh 30s</span>
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}
