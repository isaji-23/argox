// Hover tooltip rendered through a portal with fixed positioning, so it is
// never clipped by an ancestor's `overflow: hidden` (collapsed sidebar) or by
// the viewport edge (sticky header). Preferred `side` flips when space is tight.
import { useState, useRef, useLayoutEffect, type CSSProperties, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

type Side = 'top' | 'right' | 'bottom' | 'left';

interface TooltipProps {
  label: ReactNode;
  children: ReactNode;
  side?: Side;
}

const GAP = 7;
const MARGIN = 8;

export function Tooltip({ label, children, side = 'top' }: TooltipProps) {
  const [show, setShow] = useState(false);
  const triggerRef = useRef<HTMLSpanElement>(null);
  const tipRef = useRef<HTMLSpanElement>(null);
  const [coords, setCoords] = useState({ top: 0, left: 0 });

  useLayoutEffect(() => {
    if (!show || !triggerRef.current || !tipRef.current) return;
    const t = triggerRef.current.getBoundingClientRect();
    const tip = tipRef.current.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;

    let placement: Side = side;
    if (placement === 'top' && t.top - tip.height - GAP < MARGIN) placement = 'bottom';
    else if (placement === 'bottom' && t.bottom + tip.height + GAP > vh - MARGIN) placement = 'top';
    else if (placement === 'left' && t.left - tip.width - GAP < MARGIN) placement = 'right';
    else if (placement === 'right' && t.right + tip.width + GAP > vw - MARGIN) placement = 'left';

    let top = 0;
    let left = 0;
    switch (placement) {
      case 'top':
        top = t.top - tip.height - GAP;
        left = t.left + t.width / 2 - tip.width / 2;
        break;
      case 'bottom':
        top = t.bottom + GAP;
        left = t.left + t.width / 2 - tip.width / 2;
        break;
      case 'left':
        left = t.left - tip.width - GAP;
        top = t.top + t.height / 2 - tip.height / 2;
        break;
      case 'right':
        left = t.right + GAP;
        top = t.top + t.height / 2 - tip.height / 2;
        break;
    }

    left = Math.max(MARGIN, Math.min(left, vw - tip.width - MARGIN));
    top = Math.max(MARGIN, Math.min(top, vh - tip.height - MARGIN));
    setCoords({ top, left });
  }, [show, side, label]);

  const tipStyle: CSSProperties = {
    position: 'fixed',
    top: coords.top,
    left: coords.left,
    zIndex: 200,
    pointerEvents: 'none',
    background: 'var(--bg-overlay)',
    color: 'var(--text-primary)',
    border: '1px solid var(--border-strong)',
    padding: '5px 9px',
    borderRadius: 'var(--r-sm)',
    fontSize: 'var(--fs-xs)',
    whiteSpace: 'nowrap',
    boxShadow: 'var(--shadow-pop)',
    fontFamily: 'var(--font-ui)',
  };

  return (
    <span
      ref={triggerRef}
      style={{ position: 'relative', display: 'inline-flex' }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {children}
      {show &&
        createPortal(
          <span ref={tipRef} style={tipStyle}>
            {label}
          </span>,
          document.body,
        )}
    </span>
  );
}
