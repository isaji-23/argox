// Custom dropdown.
//
// The open menu is rendered through a portal to `document.body` with
// `position: fixed`, anchored to the trigger's bounding rect, so it is never
// clipped by an `overflow-hidden` ancestor (a real bug in the prior build —
// see FRONTEND_SPEC §5). Closes on outside-click and on scroll/resize.
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Icon, type IconName } from '../shared/Icon';

export interface SelectOption {
  value: string;
  label: string;
}

type RawOption = SelectOption | string;

interface SelectProps {
  value: string;
  options: RawOption[];
  onChange: (value: string) => void;
  icon?: IconName;
  minWidth?: number;
  size?: 'sm' | 'md';
}

function norm(o: RawOption): SelectOption {
  return typeof o === 'string' ? { value: o, label: o } : o;
}

export function Select({ value, options, onChange, icon, minWidth = 120, size = 'md' }: SelectProps) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [rect, setRect] = useState<DOMRect | null>(null);

  const opts = options.map(norm);
  const cur = opts.find((o) => o.value === value);
  const curLabel = cur ? cur.label : value;

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
          gap: 7,
          minWidth,
          padding: size === 'sm' ? '5px 9px' : '6px 11px',
          width: '100%',
          fontSize: 'var(--fs-sm)',
          fontWeight: 500,
          color: 'var(--text-primary)',
          background: 'var(--bg-surface-3)',
          border: '1px solid var(--border-strong)',
          borderRadius: 'var(--r-md)',
          justifyContent: 'space-between',
          transition: 'border-color var(--transition)',
        }}
      >
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, minWidth: 0 }}>
          {icon && (
            <span style={{ color: 'var(--text-muted)' }}>
              <Icon name={icon} size={14} />
            </span>
          )}
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{curLabel}</span>
        </span>
        <Icon name="chevronsUpDown" size={13} style={{ color: 'var(--text-muted)' }} />
      </button>

      {open && rect &&
        createPortal(
          <div
            ref={menuRef}
            className="ax-fade-in"
            style={{
              position: 'fixed',
              top: rect.bottom + 5,
              left: rect.left,
              minWidth: rect.width,
              zIndex: 1000,
              background: 'var(--bg-overlay)',
              border: '1px solid var(--border-strong)',
              borderRadius: 'var(--r-md)',
              boxShadow: 'var(--shadow-pop)',
              padding: 4,
              maxHeight: 280,
              overflowY: 'auto',
            }}
          >
            {opts.map((o) => {
              const sel = o.value === value;
              return (
                <button
                  key={o.value}
                  type="button"
                  onClick={() => {
                    onChange(o.value);
                    setOpen(false);
                  }}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 10,
                    width: '100%',
                    padding: '7px 9px',
                    fontSize: 'var(--fs-sm)',
                    textAlign: 'left',
                    color: sel ? 'var(--text-primary)' : 'var(--text-secondary)',
                    background: sel ? 'var(--accent-surface)' : 'transparent',
                    border: 'none',
                    borderRadius: 'var(--r-sm)',
                    whiteSpace: 'nowrap',
                  }}
                  onMouseEnter={(e) => {
                    if (!sel) e.currentTarget.style.background = 'var(--bg-surface-3)';
                  }}
                  onMouseLeave={(e) => {
                    if (!sel) e.currentTarget.style.background = 'transparent';
                  }}
                >
                  {o.label}
                  {sel && <Icon name="check" size={14} style={{ color: 'var(--accent)' }} />}
                </button>
              );
            })}
          </div>,
          document.body,
        )}
    </div>
  );
}
