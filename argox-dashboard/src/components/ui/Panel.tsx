import React, { useState } from 'react';
import { cn } from '../../lib/utils';
import { Icon } from '../shared/Icon';

interface PanelProps {
  children: React.ReactNode;
  title?: string;
  icon?: string;
  accent?: 'accent' | 'danger' | 'success' | 'warning' | 'none';
  collapsible?: boolean;
  defaultCollapsed?: boolean;
  className?: string;
  pad?: boolean;
}

export function Panel({ 
  children, 
  title, 
  icon, 
  accent = 'none', 
  collapsible = false, 
  defaultCollapsed = false,
  className, 
  pad = true 
}: PanelProps) {
  const [isCollapsed, setIsCollapsed] = useState(defaultCollapsed);

  const accents = {
    none: "",
    accent: "border-l-2 border-l-accent",
    danger: "border-l-2 border-l-block-edge",
    success: "border-l-2 border-l-allow-border",
    warning: "border-l-2 border-l-warn-border",
  };

  return (
    <div
      className={cn(
        "bg-surface border border-border rounded-lg shadow-sm overflow-hidden flex flex-col transition-all",
        accents[accent],
        className
      )}
    >
      {title && (
        <div 
          className={cn(
            "flex items-center justify-between px-4 py-2.5 border-b border-border bg-surface-2/50",
            collapsible && "cursor-pointer hover:bg-surface-3 transition-colors"
          )}
          onClick={() => collapsible && setIsCollapsed(!isCollapsed)}
        >
          <div className="flex items-center gap-2">
            {icon && <Icon name={icon} size={14} className="text-text-muted" />}
            <span className="text-xs font-bold uppercase tracking-widest text-text-muted">{title}</span>
          </div>
          {collapsible && (
            <Icon 
              name={isCollapsed ? "chevronDown" : "chevronUp"} 
              size={14} 
              className="text-text-faint" 
            />
          )}
        </div>
      )}
      {!isCollapsed && (
        <div className={cn("flex-1 overflow-hidden flex flex-col", pad && "p-4")}>
          {children}
        </div>
      )}
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
