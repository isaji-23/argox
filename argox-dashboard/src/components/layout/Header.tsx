import React from 'react';
import { cn } from '../../lib/utils';
import { Icon } from '../shared/Icon';
import { IconButton } from '../ui/Button';
import { Tooltip } from '../ui/Tooltip';
import { EnvAgentSelector } from '../ui/EnvAgentSelector';
import { TimeRangePicker } from '../ui/TimeRangePicker';

interface Breadcrumb {
  label: string;
  mono?: boolean;
  onClick?: () => void;
}

interface HeaderProps {
  title?: string;
  crumbs?: Breadcrumb[];
  theme: 'dark' | 'light';
  setTheme: (theme: 'dark' | 'light') => void;
  timeRange: string;
  setTimeRange: (range: string) => void;
  env: string;
  setEnv: (env: string) => void;
  agent: string;
  setAgent: (agent: string) => void;
  agents: string[];
  onToggleSidebar: () => void;
  showTimeControls?: boolean;
}

export function Header({
  title,
  crumbs,
  theme,
  setTheme,
  timeRange,
  setTimeRange,
  env,
  setEnv,
  agent,
  setAgent,
  agents,
  onToggleSidebar,
  showTimeControls = true
}: HeaderProps) {
  return (
    <header className="h-[56px] flex-shrink-0 flex items-center gap-3.5 px-4 border-b border-border bg-surface/80 backdrop-blur-md sticky top-0 z-40">
      <IconButton name="menu" label="Toggle sidebar" onClick={onToggleSidebar} />

      <div className="flex items-center gap-2 min-w-0">
        {crumbs ? crumbs.map((c, i) => (
          <React.Fragment key={i}>
            {i > 0 && <Icon name="chevronRight" size={13} className="text-text-faint" />}
            <span
              onClick={c.onClick}
              className={cn(
                "text-md tracking-tight whitespace-nowrap overflow-hidden text-ellipsis max-w-[320px]",
                i === crumbs.length - 1 ? "font-semibold text-text-primary" : "font-medium text-text-muted",
                c.mono ? "font-mono" : "font-ui",
                c.onClick && "cursor-pointer"
              )}
            >
              {c.label}
            </span>
          </React.Fragment>
        )) : (
          <span className="text-md font-semibold tracking-tight text-text-primary">
            {title}
          </span>
        )}
      </div>

      <div className="flex-1" />

      {showTimeControls && (
        <>
          <EnvAgentSelector
            env={env}
            setEnv={setEnv}
            agent={agent}
            setAgent={setAgent}
            agents={agents}
          />
          <TimeRangePicker value={timeRange} onChange={setTimeRange} />
        </>
      )}

      <div className="w-px h-6 bg-border mx-1" />

      <Tooltip label={theme === 'dark' ? 'Switch to light' : 'Switch to dark'}>
        <IconButton
          name={theme === 'dark' ? 'sun' : 'moon'}
          label="Theme"
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
        />
      </Tooltip>

      <button className="flex items-center gap-2 p-1 pr-1.5 rounded-full hover:bg-surface-3 transition-colors border border-transparent">
        <span className="w-7 h-7 rounded-full flex items-center justify-center bg-gradient-to-br from-peacock-cyan to-peacock-indigo text-black font-bold text-sm">
          PN
        </span>
        <Icon name="chevronDown" size={13} className="text-text-muted" />
      </button>
    </header>
  );
}
