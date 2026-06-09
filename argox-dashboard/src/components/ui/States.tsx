import React from 'react';
import { cn } from '../../lib/utils';
import { Icon } from '../shared/Icon';
import { Button } from './Button';

interface EmptyStateProps {
  icon?: string;
  title: string;
  body?: string;
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({ icon = 'layers', title, body, action, className }: EmptyStateProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center text-center p-12 px-6 gap-1", className)}>
      <div className="w-12 h-12 rounded-lg flex items-center justify-center bg-surface-3 border border-border text-text-muted mb-2">
        <Icon name={icon} size={20} />
      </div>
      <div className="text-md font-semibold text-text-primary">{title}</div>
      {body && (
        <div className="text-sm text-text-muted max-w-[360px] mt-1 leading-normal">
          {body}
        </div>
      )}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

interface ErrorStateProps {
  title?: string;
  body?: string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorState({ title = 'Failed to load', body, onRetry, className }: ErrorStateProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center text-center p-12 px-6 gap-1", className)}>
      <div className="w-12 h-12 rounded-lg flex items-center justify-center bg-block-surface border border-block-border text-block-bright mb-2">
        <Icon name="warn" size={20} />
      </div>
      <div className="text-md font-semibold text-text-primary">{title}</div>
      {body && (
        <div className="text-sm text-text-muted max-w-[380px] mt-1 leading-normal font-mono">
          {body}
        </div>
      )}
      {onRetry && (
        <div className="mt-3">
          <Button variant="secondary" icon="refresh" size="sm" onClick={onRetry}>
            Retry
          </Button>
        </div>
      )}
    </div>
  );
}

interface SkeletonProps {
  w?: string | number;
  h?: string | number;
  r?: string | number;
  className?: string;
}

export function Skeleton({ w = '100%', h = 14, r = 6, className }: SkeletonProps) {
  return (
    <div
      className={cn("bg-gradient-to-r from-skeleton-base via-skeleton-shine to-skeleton-base bg-[length:220%_100%] animate-ax-shimmer", className)}
      style={{ width: w, height: h, borderRadius: r }}
    />
  );
}
