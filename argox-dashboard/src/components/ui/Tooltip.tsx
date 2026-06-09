import React, { useState } from 'react';
import { cn } from '../../lib/utils';

interface TooltipProps {
  label: string;
  children: React.ReactNode;
  side?: 'top' | 'right' | 'bottom' | 'left';
  className?: string;
}

export function Tooltip({ label, children, side = 'top', className }: TooltipProps) {
  const [show, setShow] = useState(false);

  const positions = {
    top: "bottom-full left-1/2 -translate-x-1/2 mb-2",
    right: "left-full top-1/2 -translate-y-1/2 ml-2",
    bottom: "top-full left-1/2 -translate-x-1/2 mt-2",
    left: "right-full top-1/2 -translate-y-1/2 mr-2",
  };

  return (
    <div
      className={cn("relative inline-flex", className)}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {children}
      {show && (
        <div
          className={cn(
            "absolute z-[100] pointer-events-none bg-overlay text-text-primary border border-border-strong px-2 py-1 rounded-sm text-xs shadow-pop font-ui whitespace-nowrap ax-fade-in",
            positions[side]
          )}
        >
          {label}
        </div>
      )}
    </div>
  );
}
