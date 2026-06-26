// Generic server-side DataTable: controlled sort + pagination, row accent for
// the policy-block treatment, skeleton + empty states.
import type { ReactNode } from 'react';
import { Icon } from '../shared/Icon';
import { IconButton } from './Button';
import { Skeleton, EmptyState } from './States';
import { fmtNum } from '../../lib/utils';

export type SortDir = 'asc' | 'desc';
export interface SortState {
  key: string;
  dir: SortDir;
}

export interface Column<T> {
  key: string;
  label: string;
  width?: string;
  sortable?: boolean;
  align?: 'left' | 'right';
  render: (row: T) => ReactNode;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  loading?: boolean;
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
  sort?: SortState;
  onSort?: (key: string) => void;
  onRowClick?: (row: T) => void;
  rowKey: (row: T) => string;
  rowAccent?: (row: T) => boolean;
  empty?: { icon?: string; title: string; body?: string };
}

export function DataTable<T>({
  columns,
  rows,
  loading,
  page,
  pageSize,
  total,
  onPage,
  sort,
  onSort,
  onRowClick,
  rowKey,
  rowAccent,
  empty,
}: DataTableProps<T>) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const gridCols = columns.map((c) => c.width || '1fr').join(' ');

  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', overflow: 'hidden', background: 'var(--bg-surface)' }}>
      {/* header */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: gridCols,
          padding: '0 6px',
          background: 'var(--bg-surface-2)',
          borderBottom: '1px solid var(--border)',
        }}
      >
        {columns.map((c) => {
          const active = sort && sort.key === c.key;
          return (
            <button
              key={c.key}
              type="button"
              onClick={() => c.sortable && onSort?.(c.key)}
              disabled={!c.sortable}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 5,
                padding: '9px 10px',
                background: 'none',
                border: 'none',
                justifyContent: c.align === 'right' ? 'flex-end' : 'flex-start',
                cursor: c.sortable ? 'pointer' : 'default',
                fontSize: 'var(--fs-2xs)',
                fontWeight: 600,
                letterSpacing: '0.05em',
                textTransform: 'uppercase',
                color: active ? 'var(--text-primary)' : 'var(--text-faint)',
              }}
            >
              {c.label}
              {c.sortable &&
                (active ? (
                  <Icon name={sort!.dir === 'asc' ? 'sortAsc' : 'sortDesc'} size={13} style={{ color: 'var(--accent)' }} />
                ) : (
                  <Icon name="chevronsUpDown" size={12} style={{ opacity: 0.4 }} />
                ))}
            </button>
          );
        })}
      </div>

      {/* body */}
      <div style={{ minHeight: 120 }}>
        {loading ? (
          Array.from({ length: pageSize }).map((_, i) => (
            <div
              key={i}
              style={{ display: 'grid', gridTemplateColumns: gridCols, padding: '0 6px', borderBottom: '1px solid var(--border-faint)' }}
            >
              {columns.map((c) => (
                <div key={c.key} style={{ padding: '12px 10px' }}>
                  <Skeleton w={c.align === 'right' ? '40%' : '70%'} h={12} style={{ marginLeft: c.align === 'right' ? 'auto' : 0 }} />
                </div>
              ))}
            </div>
          ))
        ) : rows.length === 0 ? (
          <EmptyState
            icon={(empty?.icon as never) ?? 'traces'}
            title={empty?.title ?? 'No results'}
            body={empty?.body}
          />
        ) : (
          rows.map((r) => {
            const accent = rowAccent?.(r) ?? false;
            return (
              <div
                key={rowKey(r)}
                onClick={() => onRowClick?.(r)}
                style={{
                  display: 'grid',
                  gridTemplateColumns: gridCols,
                  padding: '0 6px',
                  cursor: onRowClick ? 'pointer' : 'default',
                  borderBottom: '1px solid var(--border-faint)',
                  alignItems: 'center',
                  background: accent ? 'var(--block-bg)' : 'transparent',
                  borderLeft: accent ? '2.5px solid var(--block-edge)' : '2.5px solid transparent',
                  transition: 'background var(--transition)',
                }}
                onMouseEnter={(e) => {
                  if (!accent) e.currentTarget.style.background = 'var(--bg-surface-2)';
                }}
                onMouseLeave={(e) => {
                  if (!accent) e.currentTarget.style.background = 'transparent';
                }}
              >
                {columns.map((c) => (
                  <div
                    key={c.key}
                    style={{
                      padding: '10px 10px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: c.align === 'right' ? 'flex-end' : 'flex-start',
                      minWidth: 0,
                    }}
                  >
                    {c.render(r)}
                  </div>
                ))}
              </div>
            );
          })
        )}
      </div>

      {/* footer / pagination */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          padding: '9px 14px',
          borderTop: '1px solid var(--border)',
          background: 'var(--bg-surface-2)',
        }}
      >
        <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
          {total === 0 ? '0 results' : `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)} of ${fmtNum(total)}`}
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <IconButton
            name="chevronLeft"
            label="Previous"
            onClick={() => onPage(Math.max(1, page - 1))}
            style={{ opacity: page <= 1 ? 0.4 : 1, pointerEvents: page <= 1 ? 'none' : 'auto' }}
          />
          <span
            style={{
              fontSize: 'var(--fs-xs)',
              color: 'var(--text-secondary)',
              fontFamily: 'var(--font-mono)',
              minWidth: 64,
              textAlign: 'center',
            }}
          >
            {page} / {totalPages}
          </span>
          <IconButton
            name="chevronRight"
            label="Next"
            onClick={() => onPage(Math.min(totalPages, page + 1))}
            style={{ opacity: page >= totalPages ? 0.4 : 1, pointerEvents: page >= totalPages ? 'none' : 'auto' }}
          />
        </div>
      </div>
    </div>
  );
}
