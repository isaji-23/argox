// Top header: sidebar toggle, route breadcrumbs, time controls (Metrics/Traces
// only), API-key indicator, theme toggle, avatar.
import { Fragment } from 'react';
import { Icon } from '../shared/Icon';
import { IconButton } from '../ui/Button';
import { Tooltip } from '../ui/Tooltip';
import { TimeRangePicker } from '../ui/TimeRangePicker';
import { EnvAgentSelector } from '../ui/EnvAgentSelector';
import type { TimeRange } from '../../lib/timeRange';

export interface Crumb {
  label: string;
  mono?: boolean;
  onClick?: () => void;
}

interface HeaderProps {
  crumbs: Crumb[];
  theme: 'dark' | 'light';
  setTheme: (t: 'dark' | 'light') => void;
  timeRange: TimeRange;
  setTimeRange: (t: TimeRange) => void;
  env: string;
  setEnv: (v: string) => void;
  agent: string;
  setAgent: (v: string) => void;
  showTimeControls?: boolean;
  hasCredential: boolean;
  onOpenAuth: () => void;
}

export function Header({
  crumbs,
  theme,
  setTheme,
  timeRange,
  setTimeRange,
  env,
  setEnv,
  agent,
  setAgent,
  showTimeControls = true,
  hasCredential,
  onOpenAuth,
}: HeaderProps) {
  return (
    <header
      style={{
        height: 56,
        flex: '0 0 auto',
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        padding: '0 18px',
        borderBottom: '1px solid var(--border)',
        background: 'color-mix(in srgb, var(--bg-surface) 82%, transparent)',
        backdropFilter: 'blur(10px)',
        position: 'sticky',
        top: 0,
        zIndex: 40,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
        {crumbs.map((c, i) => (
          <Fragment key={i}>
            {i > 0 && <Icon name="chevronRight" size={13} style={{ color: 'var(--text-faint)' }} />}
            <span
              onClick={c.onClick}
              style={{
                fontSize: 'var(--fs-md)',
                fontWeight: i === crumbs.length - 1 ? 600 : 500,
                color: i === crumbs.length - 1 ? 'var(--text-primary)' : 'var(--text-muted)',
                fontFamily: c.mono ? 'var(--font-mono)' : 'var(--font-ui)',
                letterSpacing: '-0.01em',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                maxWidth: 320,
                cursor: c.onClick ? 'pointer' : 'default',
              }}
            >
              {c.label}
            </span>
          </Fragment>
        ))}
      </div>

      <div style={{ flex: 1 }} />

      {showTimeControls && (
        <>
          <EnvAgentSelector env={env} setEnv={setEnv} agent={agent} setAgent={setAgent} />
          <TimeRangePicker value={timeRange} onChange={setTimeRange} />
        </>
      )}

      <Tooltip label={hasCredential ? 'API key set' : 'No API key — click to add'}>
        <IconButton name={hasCredential ? 'eye' : 'eyeOff'} label="API key" active={hasCredential} onClick={onOpenAuth} />
      </Tooltip>

      <div style={{ width: 1, height: 24, background: 'var(--border)' }} />

      <Tooltip label={theme === 'dark' ? 'Switch to light' : 'Switch to dark'}>
        <IconButton name={theme === 'dark' ? 'sun' : 'moon'} label="Theme" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} />
      </Tooltip>

      <button
        type="button"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 9,
          padding: '4px 6px 4px 4px',
          background: 'transparent',
          border: '1px solid transparent',
          borderRadius: 'var(--r-full)',
        }}
        onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-surface-3)')}
        onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
      >
        <span
          style={{
            width: 28,
            height: 28,
            borderRadius: 999,
            display: 'grid',
            placeItems: 'center',
            background: 'linear-gradient(135deg, var(--peacock-cyan), var(--peacock-indigo))',
            color: '#04121A',
            fontWeight: 700,
            fontSize: 'var(--fs-sm)',
          }}
        >
          PN
        </span>
        <Icon name="chevronDown" size={13} style={{ color: 'var(--text-muted)' }} />
      </button>
    </header>
  );
}
