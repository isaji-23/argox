// Persistent left sidebar: brand, nav groups (Observe / Manage), collector
// health footer. Collapsible to a 60px icon-only rail.
import { NavLink } from 'react-router-dom';
import { Logo } from '../shared/Logo';
import { Icon, type IconName } from '../shared/Icon';
import { Tooltip } from '../ui/Tooltip';

interface NavItem {
  to: string;
  label: string;
  icon: IconName;
}

const GROUPS: { title: string; items: NavItem[] }[] = [
  {
    title: 'Observe',
    items: [
      { to: '/metrics', label: 'Metrics', icon: 'metrics' },
      { to: '/traces', label: 'Traces', icon: 'traces' },
      { to: '/policies', label: 'Policies', icon: 'policies' },
    ],
  },
  {
    title: 'Manage',
    items: [{ to: '/keys', label: 'API keys', icon: 'keys' }],
  },
];

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  return (
    <div style={{ position: 'relative', flex: '0 0 auto', height: '100%' }}>
      <aside
        style={{
          width: collapsed ? 60 : 220,
          flex: `0 0 ${collapsed ? 60 : 220}px`,
          background: 'var(--bg-surface)',
          borderRight: '1px solid var(--border)',
          display: 'flex',
          flexDirection: 'column',
          transition: 'width var(--transition-slow), flex-basis var(--transition-slow)',
          height: '100%',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            height: 56,
            display: 'flex',
            alignItems: 'center',
            padding: collapsed ? 0 : '0 16px',
            justifyContent: collapsed ? 'center' : 'flex-start',
            borderBottom: '1px solid var(--border)',
            flex: '0 0 auto',
          }}
        >
          <Logo withWord={!collapsed} size={26} />
        </div>

        <nav style={{ padding: collapsed ? '12px 10px' : '12px 12px', display: 'flex', flexDirection: 'column', gap: 3, flex: 1, overflowY: 'auto' }}>
          {GROUPS.map((group) => (
            <div key={group.title} style={{ display: 'flex', flexDirection: 'column', gap: 3, marginBottom: 6, alignItems: collapsed ? 'center' : 'stretch' }}>
              {!collapsed && (
                <div
                  style={{
                    padding: '6px 8px 4px',
                    fontSize: 'var(--fs-2xs)',
                    fontWeight: 600,
                    letterSpacing: '0.07em',
                    textTransform: 'uppercase',
                    color: 'var(--text-faint)',
                  }}
                >
                  {group.title}
                </div>
              )}
              {group.items.map((n) => {
                const link = (
                  <NavLink to={n.to} style={{ width: collapsed ? 'auto' : '100%' }}>
                    {({ isActive }) => (
                      <span
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 11,
                          width: collapsed ? 40 : '100%',
                          padding: collapsed ? 0 : '8px 10px',
                          height: collapsed ? 40 : 'auto',
                          flex: '0 0 auto',
                          justifyContent: collapsed ? 'center' : 'flex-start',
                          fontSize: 'var(--fs-base)',
                          fontWeight: 520,
                          position: 'relative',
                          color: isActive ? 'var(--accent)' : 'var(--text-secondary)',
                          background: isActive ? 'var(--accent-surface)' : 'transparent',
                          border: '1px solid ' + (isActive ? 'var(--accent-border)' : 'transparent'),
                          borderRadius: 'var(--r-md)',
                          transition: 'all var(--transition)',
                        }}
                        onMouseEnter={(e) => {
                          if (!isActive) {
                            e.currentTarget.style.background = 'var(--bg-surface-3)';
                            e.currentTarget.style.color = 'var(--text-primary)';
                          }
                        }}
                        onMouseLeave={(e) => {
                          if (!isActive) {
                            e.currentTarget.style.background = 'transparent';
                            e.currentTarget.style.color = 'var(--text-secondary)';
                          }
                        }}
                      >
                        {isActive && !collapsed && (
                          <span style={{ position: 'absolute', left: -12, top: 8, bottom: 8, width: 2.5, borderRadius: 2, background: 'var(--accent)' }} />
                        )}
                        <Icon name={n.icon} size={17} />
                        {!collapsed && n.label}
                      </span>
                    )}
                  </NavLink>
                );
                // Tooltip only adds value when the label is hidden (collapsed rail).
                return collapsed ? (
                  <Tooltip key={n.to} label={n.label} side="right">{link}</Tooltip>
                ) : (
                  <span key={n.to} style={{ display: 'flex' }}>{link}</span>
                );
              })}
            </div>
          ))}
        </nav>

        <div style={{ padding: collapsed ? '10px' : '12px', borderTop: '1px solid var(--border)', flex: '0 0 auto' }}>
          {!collapsed ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 6px' }}>
              <span style={{ width: 7, height: 7, borderRadius: 999, background: 'var(--allow)', boxShadow: '0 0 0 3px var(--allow-surface)' }} />
              <span style={{ fontSize: 'var(--fs-2xs)', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>collector · healthy</span>
            </div>
          ) : (
            <div style={{ display: 'grid', placeItems: 'center' }}>
              <span style={{ width: 7, height: 7, borderRadius: 999, background: 'var(--allow)', boxShadow: '0 0 0 3px var(--allow-surface)' }} />
            </div>
          )}
        </div>
      </aside>

      <button
        type="button"
        onClick={onToggle}
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        style={{
          position: 'absolute',
          top: '50%',
          right: -12,
          transform: 'translateY(-50%)',
          zIndex: 50,
          width: 24,
          height: 24,
          boxSizing: 'border-box',
          borderRadius: 999,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 0,
          lineHeight: 0,
          background: 'var(--bg-surface)',
          border: '1px solid var(--border)',
          color: 'var(--text-muted)',
          boxShadow: 'var(--shadow-sm)',
          cursor: 'pointer',
          transition: 'all var(--transition)',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = 'var(--bg-surface-3)';
          e.currentTarget.style.color = 'var(--text-primary)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = 'var(--bg-surface)';
          e.currentTarget.style.color = 'var(--text-muted)';
        }}
      >
        <Icon name={collapsed ? 'chevronRight' : 'chevronLeft'} size={14} />
      </button>
    </div>
  );
}
