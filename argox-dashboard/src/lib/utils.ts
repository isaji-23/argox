import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function fmtMs(ms: number): string {
  return ms >= 1000 ? (ms / 1000).toFixed(2) + 's' : Math.round(ms) + 'ms';
}

/** Formats a USD amount: 4 decimals under $1, otherwise 2. */
export function fmtUsd(n: number): string {
  const v = n || 0;
  return '$' + v.toFixed(v < 1 ? 4 : 2);
}

/** Formats an integer with thousands separators (en-US). */
export function fmtNum(n: number): string {
  return Math.round(n || 0).toLocaleString('en-US');
}

/** Formats a token count compactly (e.g. 8420 -> "8.4k"). */
export function fmtCompact(n: number): string {
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
  return String(n || 0);
}
