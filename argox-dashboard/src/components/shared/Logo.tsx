import { useId } from 'react';
import { cn } from '../../lib/utils';

interface LogoProps {
  size?: number;
  withWord?: boolean;
  className?: string;
}

export function Logo({ size = 26, withWord = true, className }: LogoProps) {
  const id = useId();
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <svg width={size} height={size} viewBox="0 0 40 40" fill="none" className="block">
        <defs>
          <radialGradient id={id} cx="50%" cy="50%" r="60%">
            <stop offset="0%" stopColor="var(--peacock-cyan-bright)" />
            <stop offset="42%" stopColor="var(--peacock-cyan)" />
            <stop offset="74%" stopColor="var(--peacock-indigo)" />
            <stop offset="100%" stopColor="var(--bronze)" />
          </radialGradient>
        </defs>
        <path
          d="M20 6c9 0 16 8.5 16 14s-7 8-16 8S4 25.5 4 20 11 6 20 6z"
          stroke={`url(#${id})`}
          strokeWidth="2.4"
          fill="none"
          className="opacity-90"
        />
        <circle
          cx="20"
          cy="20"
          r="8.6"
          stroke="var(--bronze)"
          strokeWidth="1.5"
          fill="none"
          className="opacity-70"
        />
        <circle cx="20" cy="20" r="5" fill={`url(#${id})`} />
        <circle cx="20" cy="20" r="2" fill="var(--bg-base)" />
      </svg>
      {withWord && (
        <span className="font-display font-bold text-lg tracking-tight text-text-primary">
          Argox
        </span>
      )}
    </div>
  );
}
