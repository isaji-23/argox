// Loading / empty / error states + skeletons.
import type { CSSProperties, ReactNode } from 'react';
import { Icon, type IconName } from '../shared/Icon';
import { Button } from './Button';

interface SkeletonProps {
  w?: number | string;
  h?: number | string;
  r?: number;
  style?: CSSProperties;
}

export function Skeleton({ w = '100%', h = 14, r = 6, style }: SkeletonProps) {
  return (
    <div
      style={{
        width: w,
        height: h,
        borderRadius: r,
        background:
          'linear-gradient(90deg, var(--skeleton-base) 25%, var(--skeleton-shine) 50%, var(--skeleton-base) 75%)',
        backgroundSize: '220% 100%',
        animation: 'ax-shimmer 1.4s linear infinite',
        ...style,
      }}
    />
  );
}

export function ChartSkeleton({ height = 188 }: { height?: number }) {
  return (
    <div style={{ height, display: 'flex', alignItems: 'flex-end', gap: 8, padding: '8px 4px' }}>
      {[40, 65, 50, 80, 60, 90, 70, 55, 75, 45, 85, 62].map((h, i) => (
        <Skeleton key={i} w="100%" h={`${h}%`} r={4} />
      ))}
    </div>
  );
}

interface EmptyStateProps {
  icon?: IconName;
  title: ReactNode;
  body?: ReactNode;
  action?: ReactNode;
}

export function EmptyState({ icon = 'layers', title, body, action }: EmptyStateProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
        padding: '52px 24px',
        gap: 4,
      }}
    >
      <div
        style={{
          width: 46,
          height: 46,
          borderRadius: 'var(--r-lg)',
          display: 'grid',
          placeItems: 'center',
          background: 'var(--bg-surface-3)',
          border: '1px solid var(--border)',
          color: 'var(--text-muted)',
          marginBottom: 8,
        }}
      >
        <Icon name={icon} size={20} />
      </div>
      <div style={{ fontSize: 'var(--fs-md)', fontWeight: 600, color: 'var(--text-primary)' }}>{title}</div>
      {body && <div style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-muted)', maxWidth: 360, lineHeight: 1.5 }}>{body}</div>}
      {action && <div style={{ marginTop: 12 }}>{action}</div>}
    </div>
  );
}

interface ErrorStateProps {
  title?: ReactNode;
  body?: ReactNode;
  onRetry?: () => void;
}

export function ErrorState({ title = 'Failed to load', body, onRetry }: ErrorStateProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
        padding: '48px 24px',
        gap: 4,
      }}
    >
      <div
        style={{
          width: 46,
          height: 46,
          borderRadius: 'var(--r-lg)',
          display: 'grid',
          placeItems: 'center',
          background: 'var(--block-surface)',
          border: '1px solid var(--block-border)',
          color: 'var(--block-bright)',
          marginBottom: 8,
        }}
      >
        <Icon name="warn" size={20} />
      </div>
      <div style={{ fontSize: 'var(--fs-md)', fontWeight: 600, color: 'var(--text-primary)' }}>{title}</div>
      {body && (
        <div
          style={{
            fontSize: 'var(--fs-sm)',
            color: 'var(--text-muted)',
            maxWidth: 380,
            lineHeight: 1.5,
            fontFamily: 'var(--font-mono)',
          }}
        >
          {body}
        </div>
      )}
      {onRetry && (
        <div style={{ marginTop: 12 }}>
          <Button variant="secondary" icon="refresh" size="sm" onClick={onRetry}>
            Retry
          </Button>
        </div>
      )}
    </div>
  );
}
