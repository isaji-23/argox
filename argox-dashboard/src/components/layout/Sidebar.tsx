import { cn } from '../../lib/utils';
import { Icon } from '../shared/Icon';
import { Logo } from '../shared/Logo';
import { Tooltip } from '../ui/Tooltip';

export const NAV_ITEMS = [
  { id: 'metrics',  label: 'Metrics',  icon: 'metrics' },
  { id: 'traces',   label: 'Traces',   icon: 'traces' },
  { id: 'policies', label: 'Policies', icon: 'policies' },
];

interface SidebarProps {
  route: string;
  setRoute: (route: string) => void;
  collapsed: boolean;
}

export function Sidebar({ route, setRoute, collapsed }: SidebarProps) {
  return (
    <aside
      className={cn(
        "bg-surface border-r border-border flex flex-col transition-[width] duration-240 h-full overflow-hidden",
        collapsed ? "w-[60px]" : "w-[220px]"
      )}
    >
      <div className={cn(
        "h-[56px] flex items-center border-b border-border flex-shrink-0",
        collapsed ? "justify-center px-0" : "justify-start px-4"
      )}>
        <Logo withWord={!collapsed} size={26} />
      </div>

      <nav className={cn(
        "flex flex-col gap-1 p-3",
        collapsed ? "px-2.5" : "px-3"
      )}>
        {!collapsed && (
          <div className="px-2 py-1 text-2xs font-semibold tracking-widest uppercase text-text-faint mb-1">
            Observe
          </div>
        )}
        {NAV_ITEMS.map((n) => {
          const active = route === n.id;
          return (
            <Tooltip key={n.id} label={n.label} side="right">
              <button
                onClick={() => setRoute(n.id)}
                className={cn(
                  "flex items-center gap-3 w-full rounded-md font-medium text-base relative transition-all group",
                  collapsed ? "h-10 justify-center p-0" : "p-2 justify-start",
                  active
                    ? "text-accent bg-accent-surface border-accent-border border"
                    : "text-text-secondary bg-transparent border-transparent hover:bg-surface-3 hover:text-text-primary"
                )}
              >
                {active && !collapsed && (
                  <span className="absolute -left-3 top-2 bottom-2 w-[2.5px] rounded-r-sm bg-accent" />
                )}
                <Icon name={n.icon} size={17} />
                {!collapsed && <span>{n.label}</span>}
              </button>
            </Tooltip>
          );
        })}
      </nav>

      <div className="mt-auto p-3 border-t border-border">
        <Tooltip label="Design system" side="right">
          <button
            onClick={() => setRoute('system')}
            className={cn(
              "flex items-center gap-3 w-full rounded-md font-medium text-base transition-all",
              collapsed ? "h-10 justify-center p-0" : "p-2 justify-start",
              route === 'system'
                ? "text-accent bg-accent-surface border-accent-border border"
                : "text-text-muted bg-transparent hover:bg-surface-3 hover:text-text-primary"
            )}
          >
            <Icon name="system" size={17} />
            {!collapsed && <span>Design system</span>}
          </button>
        </Tooltip>
        {!collapsed && (
          <div className="flex items-center gap-2 px-2 pt-2.5 mt-1">
            <span className="w-1.5 h-1.5 rounded-full bg-allow shadow-[0_0_0_3px_var(--allow-surface)]" />
            <span className="text-2xs text-text-muted font-mono uppercase tracking-tight">
              collector · healthy
            </span>
          </div>
        )}
      </div>
    </aside>
  );
}
