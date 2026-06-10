import React from 'react';
import { cn } from '../../lib/utils';

export const ICON_PATHS: Record<string, string> = {
  metrics: 'M3 3v18h18 M7 14l3-4 3 3 4-6',
  traces: 'M4 5h10 M4 12h7 M4 19h13 M18 5h2 M14 12h2 M19 12h1',
  policies: 'M12 3l7 3v5c0 4.5-3 7.6-7 9-4-1.4-7-4.5-7-9V6z M9 12l2 2 4-4',
  system: 'M4 5h7v7H4z M13 5h7v4h-7z M13 12h7v7h-7z M4 14h7v5H4z',
  search: 'M11 4a7 7 0 105.2 11.7L20 20 M11 4a7 7 0 010 14',
  clock: 'M12 7v5l3 2 M12 3a9 9 0 100 18 9 9 0 000-18z',
  chevronDown: 'M6 9l6 6 6-6',
  chevronRight: 'M9 6l6 6-6 6',
  chevronLeft: 'M15 6l-6 6 6 6',
  chevronsUpDown: 'M8 9l4-4 4 4 M8 15l4 4 4-4',
  sun: 'M12 4V2 M12 22v-2 M4 12H2 M22 12h-2 M5.6 5.6L4.2 4.2 M19.8 19.8l-1.4-1.4 M18.4 5.6l1.4-1.4 M4.2 19.8l1.4-1.4 M12 8a4 4 0 100 8 4 4 0 000-8z',
  moon: 'M20 14.5A8 8 0 019.5 4 7 7 0 1020 14.5z',
  user: 'M5 20a7 7 0 0114 0 M12 11a4 4 0 100-8 4 4 0 000 8z',
  check: 'M5 12.5l4.5 4.5L19 7',
  x: 'M6 6l12 12 M18 6L6 18',
  ban: 'M5.5 5.5l13 13 M12 3a9 9 0 100 18 9 9 0 000-18z',
  warn: 'M12 4l9 16H3z M12 10v4 M12 17.5v.5',
  filter: 'M4 5h16l-6 7v6l-4 2v-8z',
  copy: 'M9 9h10v10H9z M5 15V5h10',
  play: 'M7 5l11 7-11 7z',
  save: 'M5 4h11l3 3v13H5z M8 4v5h7V4 M8 20v-6h8v6',
  diff: 'M6 3v6 M3 6h6 M5 18h6 M18 15v6 M15 18h6 M14 5l5 5',
  plus: 'M12 5v14 M5 12h14',
  refresh: 'M20 11a8 8 0 10-1.5 5 M20 5v6h-6',
  external: 'M14 4h6v6 M20 4l-9 9 M18 14v5H5V6h5',
  database: 'M12 3c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3z M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6 M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6',
  llm: 'M12 4a4 4 0 014 4 3.5 3.5 0 011 6 3.5 3.5 0 01-5 3 3.5 3.5 0 01-5-3 3.5 3.5 0 011-6 4 4 0 014-4z M12 8v9',
  tool: 'M14.7 6.3a4 4 0 00-5.4 5.4l-5 5a2 2 0 102.8 2.8l5-5a4 4 0 005.4-5.4l-2.5 2.5-2.1-2.1z',
  processor: 'M9 9h6v6H9z M12 3v3 M12 18v3 M3 12h3 M18 12h3 M5 5l2 2 M17 17l2 2 M19 5l-2 2 M7 17l-2 2',
  layers: 'M12 3l9 5-9 5-9-5z M3 13l9 5 9-5 M3 17l9 5 9-5',
  dot: 'M12 12m-3 0a3 3 0 106 0 3 3 0 10-6 0',
  eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z M12 9a3 3 0 100 6 3 3 0 000-6z',
  sortAsc: 'M7 17V7 M4 10l3-3 3 3 M13 7h7 M13 12h5 M13 17h3',
  sortDesc: 'M7 7v10 M4 14l3 3 3-3 M13 7h3 M13 12h5 M13 17h7',
  shieldAlert: 'M12 3l7 3v5c0 4.5-3 7.6-7 9-4-1.4-7-4.5-7-9V6z M12 8v4 M12 15v.5',
  arrowRight: 'M5 12h14 M13 6l6 6-6 6',
  menu: 'M4 6h16 M4 12h16 M4 18h16',
  bolt: 'M13 3L4 14h6l-1 7 9-11h-6z',
  hash: 'M9 3L7 21 M17 3l-2 18 M4 8h16 M3 16h16',
  download: 'M12 4v11 M8 11l4 4 4-4 M5 20h14',
  gauge: 'M12 13l4-4 M12 21a9 9 0 110-18 9 9 0 016.4 15.4 M12 13a1.5 1.5 0 100-3 1.5 1.5 0 000 3z',
  dollar: 'M12 3v18 M16 7.5C16 5.6 14.2 4 12 4S8 5.6 8 7.5 9.8 11 12 11s4 1.6 4 3.5-1.8 3.5-4 3.5-4-1.6-4-3.5',
  spark: 'M12 3l2.2 6.2L20 11l-5.8 1.8L12 19l-2.2-6.2L4 11l5.8-1.8z',
};

interface IconProps extends React.SVGProps<SVGSVGElement> {
  name: string;
  size?: number;
  strokeWidth?: number;
}

export function Icon({ name, size = 16, strokeWidth = 1.7, className, ...props }: IconProps) {
  const d = ICON_PATHS[name];
  if (!d) return null;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn("flex-shrink-0 block", className)}
      aria-hidden="true"
      {...props}
    >
      {d.split(' M').map((seg, i) => (
        <path key={i} d={(i ? 'M' : '') + seg} />
      ))}
    </svg>
  );
}
