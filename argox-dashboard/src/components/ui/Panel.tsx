import React from 'react';
import { cn } from '../../lib/utils';
import { Icon } from '../shared/Icon';

interface PanelProps {
  children: React.ReactNode;
  className?: string;
  pad?: boolean;
}

export function Panel({ children, className, pad = true }: PanelProps) {
  return (
    <div
      className={cn(
        "bg-surface border border-border rounded-lg shadow-sm overflow-hidden",
        pad && "p-5",
        className
      )}
    >
      {children}
    </div>
  );
}

interface PanelHeaderProps {
  title: string;
  subtitle?: string;
  icon?: string;
  right?: React.ReactNode;
  className?: string;
}

export function PanelHeader({ title, subtitle, icon, right, className }: PanelHeaderProps) {
  return (
    <div className={cn("flex items-start justify-between gap-3 mb-1", className)}>
      <div className="flex items-center gap-2.5 min-w-0">
        {icon && <Icon name={icon} size={16} className="text-text-muted" />}
        <div className="min-w-0">
          <div className="text-md font-semibold text-text-primary tracking-tight leading-tight">
            {title}
          </div>
          {subtitle && (
            <div className="text-sm text-text-muted mt-0.5 leading-snug">
              {subtitle}
            </div>
          )}
        </div>
      </div>
      {right}
    </div>
  );
}
