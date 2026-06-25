// Time-range options shared by the header picker and the data screens.

export type TimeRange = '1h' | '24h' | '7d' | '30d';

export interface TimeRangeOption {
  value: TimeRange;
  label: string;
}

export const TIME_RANGES: TimeRangeOption[] = [
  { value: '1h', label: 'Last 1 hour' },
  { value: '24h', label: 'Last 24 hours' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
];

const HOURS: Record<TimeRange, number> = { '1h': 1, '24h': 24, '7d': 168, '30d': 720 };

/** Converts a UI range token to the `window_hours` query value. */
export function rangeToHours(range: TimeRange): number {
  return HOURS[range] ?? 24;
}

/** Human label for a range token (e.g. "Last 24 hours"). */
export function rangeLabel(range: TimeRange): string {
  return TIME_RANGES.find((r) => r.value === range)?.label ?? range;
}
