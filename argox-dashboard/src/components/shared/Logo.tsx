// Argox eye-mark — peacock iridescent radial gradient with a bronze ring.
import { useId } from 'react';

interface LogoProps {
  size?: number;
  withWord?: boolean;
}

export function Logo({ size = 26, withWord = true }: LogoProps) {
  // Stable, render-pure gradient id (colons stripped so url(#id) stays valid).
  const id = 'lg' + useId().replace(/:/g, '');
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <svg width={size} height={size} viewBox="0 0 40 40" fill="none" style={{ display: 'block' }}>
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
          opacity="0.9"
        />
        <circle cx="20" cy="20" r="8.6" stroke="var(--bronze)" strokeWidth="1.5" fill="none" opacity="0.7" />
        <circle cx="20" cy="20" r="5" fill={`url(#${id})`} />
        <circle cx="20" cy="20" r="2" fill="var(--bg-base)" />
      </svg>
      {withWord && (
        <span
          style={{
            fontFamily: 'var(--font-display)',
            fontWeight: 700,
            fontSize: 17,
            letterSpacing: '-0.01em',
            color: 'var(--text-primary)',
          }}
        >
          Argox
        </span>
      )}
    </div>
  );
}
