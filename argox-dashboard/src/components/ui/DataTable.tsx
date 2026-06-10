import React from 'react';
import { cn } from '../../lib/utils';
import { Icon } from '../shared/Icon';
import { IconButton } from '../ui/Button';
import { Skeleton, EmptyState } from './States';

export interface Column<T> {
  key: string;
  label: string;
  width?: string;
  sortable?: boolean;
  align?: 'left' | 'right' | 'center';
  render: (row: T) => React.ReactNode;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  loading?: boolean;
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
  sort?: { key: string; dir: 'asc' | 'desc' };
  onSort: (key: string) => void;
  onRowClick?: (row: T) => void;
  rowKey: (row: T) => string | number;
  rowAccent?: (row: T) => boolean;
  className?: string;
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
  className
}: DataTableProps<T>) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const gridCols = columns.map((c) => c.width || '1fr').join(' ');

  return (
    <div className={cn("border border-border rounded-lg overflow-hidden bg-surface", className)}>
      {/* Header */}
      <div
        className="grid bg-surface-2 border-b border-border px-1.5"
        style={{ gridTemplateColumns: gridCols }}
      >
        {columns.map((c) => {
          const isActive = sort && sort.key === c.key;
          return (
            <button
              key={c.key}
              onClick={() => c.sortable && onSort(c.key)}
              disabled={!c.sortable}
              className={cn(
                "flex items-center gap-1.5 p-2.5 text-2xs font-bold tracking-widest uppercase transition-colors",
                c.align === 'right' ? "justify-end" : "justify-start",
                c.sortable ? "cursor-pointer" : "cursor-default",
                isActive ? "text-text-primary" : "text-text-faint"
              )}
            >
              {c.label}
              {c.sortable && (
                isActive ? (
                  <Icon
                    name={sort.dir === 'asc' ? 'sortAsc' : 'sortDesc'}
                    size={13}
                    className="text-accent"
                  />
                ) : (
                  <Icon name="chevronsUpDown" size={12} className="opacity-40" />
                )
              )}
            </button>
          );
        })}
      </div>

      {/* Body */}
      <div className="min-h-[120px]">
        {loading ? (
          Array.from({ length: pageSize }).map((_, i) => (
            <div
              key={i}
              className="grid px-1.5 border-b border-border-faint last:border-0"
              style={{ gridTemplateColumns: gridCols }}
            >
              {columns.map((c) => (
                <div key={c.key} className="p-3">
                  <Skeleton
                    w={c.align === 'right' ? '40%' : '70%'}
                    h={12}
                    className={c.align === 'right' ? 'ml-auto' : 'ml-0'}
                  />
                </div>
              ))}
            </div>
          ))
        ) : rows.length === 0 ? (
          <EmptyState
            icon="traces"
            title="No results match these filters"
            body="Try widening the time range or clearing the status / decision filters."
          />
        ) : (
          rows.map((r) => {
            const hasAccent = rowAccent && rowAccent(r);
            return (
              <div
                key={rowKey(r)}
                onClick={() => onRowClick && onRowClick(r)}
                className={cn(
                  "grid px-1.5 border-b border-border-faint last:border-0 items-center transition-colors group",
                  onRowClick ? "cursor-pointer" : "cursor-default",
                  hasAccent ? "bg-block-bg border-l-[2.5px] border-l-block-edge" : "bg-transparent border-l-[2.5px] border-l-transparent hover:bg-surface-2"
                )}
                style={{ gridTemplateColumns: gridCols }}
              >
                {columns.map((c) => (
                  <div
                    key={c.key}
                    className={cn(
                      "p-2.5 flex items-center min-w-0",
                      c.align === 'right' ? "justify-end" : "justify-start"
                    )}
                  >
                    {c.render(r)}
                  </div>
                ))}
              </div>
            );
          })
        )}
      </div>

      {/* Footer / Pagination */}
      <div className="flex items-center justify-between gap-3 px-3.5 py-2.5 border-t border-border bg-surface-2">
        <span className="text-xs text-text-muted font-mono uppercase tracking-tighter">
          {total === 0
            ? '0 results'
            : `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)} of ${total.toLocaleString()}`}
        </span>
        <div className="flex items-center gap-1.5">
          <IconButton
            name="chevronLeft"
            label="Previous"
            onClick={() => onPage(Math.max(1, page - 1))}
            disabled={page <= 1}
            className={page <= 1 ? "opacity-40 cursor-not-allowed" : ""}
          />
          <span className="text-xs text-text-secondary font-mono min-w-[64px] text-center">
            {page} / {totalPages}
          </span>
          <IconButton
            name="chevronRight"
            label="Next"
            onClick={() => onPage(Math.min(totalPages, page + 1))}
            disabled={page >= totalPages}
            className={page >= totalPages ? "opacity-40 cursor-not-allowed" : ""}
          />
        </div>
      </div>
    </div>
  );
}
