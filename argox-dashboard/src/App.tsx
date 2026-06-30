// App shell: routing, theme, time/env/agent controls, and the read-key auth
// flow. The URL is the source of truth for navigation (deep-linkable).
import { useEffect, useMemo, useState } from 'react';
import {
  Navigate,
  Outlet,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useOutletContext,
  useParams,
} from 'react-router-dom';
import { Sidebar } from './components/layout/Sidebar';
import { Header, type Crumb } from './components/layout/Header';
import { AuthDialog } from './components/ui/AuthDialog';
import { ToastProvider } from './components/ui/Toast';
import {
  authBus,
  getToken,
  AUTH_REQUIRED_EVENT,
  TOKEN_CHANGED_EVENT,
} from './lib/auth';
import type { TimeRange } from './lib/timeRange';
import { MetricsScreen } from './components/screens/MetricsScreen';
import { TracesScreen } from './components/screens/TracesScreen';
import { TraceDetailScreen } from './components/screens/TraceDetailScreen';
import { PoliciesScreen } from './components/screens/PoliciesScreen';
import { KeysScreen } from './components/screens/KeysScreen';

/** Cross-cutting state handed to every screen via the router outlet. */
export interface ShellContext {
  timeRange: TimeRange;
  env: string;
  agent: string;
  /** Bumped whenever a credential changes; screens depend on it to refetch. */
  reloadKey: number;
}

export function useShell() {
  return useOutletContext<ShellContext>();
}

type Theme = 'dark' | 'light';

function Layout(props: {
  theme: Theme;
  setTheme: (t: Theme) => void;
  timeRange: TimeRange;
  setTimeRange: (t: TimeRange) => void;
  env: string;
  setEnv: (v: string) => void;
  agent: string;
  setAgent: (v: string) => void;
  collapsed: boolean;
  toggleSidebar: () => void;
  hasCredential: boolean;
  openAuth: () => void;
  reloadKey: number;
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const params = useParams();

  const path = location.pathname;
  const showTimeControls = path === '/metrics' || path === '/traces';

  const crumbs: Crumb[] = useMemo(() => {
    if (path.startsWith('/traces/')) {
      return [
        { label: 'Traces', onClick: () => navigate('/traces') },
        { label: params.traceId ?? 'trace', mono: true },
      ];
    }
    if (path.startsWith('/metrics')) return [{ label: 'Metrics' }];
    if (path.startsWith('/traces')) return [{ label: 'Traces' }];
    if (path.startsWith('/policies')) return [{ label: 'Policies' }];
    if (path.startsWith('/keys')) return [{ label: 'API keys' }];
    return [{ label: 'Argox' }];
  }, [path, params.traceId, navigate]);

  const ctx: ShellContext = {
    timeRange: props.timeRange,
    env: props.env,
    agent: props.agent,
    reloadKey: props.reloadKey,
  };

  return (
    <div style={{ display: 'flex', height: '100%' }}>
      <Sidebar collapsed={props.collapsed} onToggle={props.toggleSidebar} />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, height: '100%' }}>
        <Header
          crumbs={crumbs}
          theme={props.theme}
          setTheme={props.setTheme}
          timeRange={props.timeRange}
          setTimeRange={props.setTimeRange}
          env={props.env}
          setEnv={props.setEnv}
          agent={props.agent}
          setAgent={props.setAgent}
          showTimeControls={showTimeControls}
          hasCredential={props.hasCredential}
          onOpenAuth={props.openAuth}
        />
        <main style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
          <Outlet context={ctx} />
        </main>
      </div>
    </div>
  );
}

export default function App() {
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem('argox.theme') as Theme) || 'dark');
  const [timeRange, setTimeRange] = useState<TimeRange>('24h');
  const [env, setEnv] = useState('production');
  const [agent, setAgent] = useState('all');
  const [collapsed, setCollapsed] = useState(false);
  const [authOpen, setAuthOpen] = useState(false);
  const [authPrompted, setAuthPrompted] = useState(false);
  const [hasCredential, setHasCredential] = useState(() => !!getToken());
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('argox.theme', theme);
  }, [theme]);

  // Auth bus + cross-tab sync.
  useEffect(() => {
    const onAuthRequired = () => {
      setAuthPrompted(true);
      setAuthOpen(true);
    };
    const onTokenChanged = () => {
      setHasCredential(!!getToken());
      setReloadKey((k) => k + 1);
    };
    const onStorage = (e: StorageEvent) => {
      if (e.key === 'argox.apikey') onTokenChanged();
    };
    authBus.addEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
    authBus.addEventListener(TOKEN_CHANGED_EVENT, onTokenChanged);
    window.addEventListener('storage', onStorage);
    return () => {
      authBus.removeEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
      authBus.removeEventListener(TOKEN_CHANGED_EVENT, onTokenChanged);
      window.removeEventListener('storage', onStorage);
    };
  }, []);

  const openAuth = () => {
    setAuthPrompted(false);
    setAuthOpen(true);
  };

  return (
    <ToastProvider>
      <Routes>
        <Route
          element={
            <Layout
              theme={theme}
              setTheme={setTheme}
              timeRange={timeRange}
              setTimeRange={setTimeRange}
              env={env}
              setEnv={setEnv}
              agent={agent}
              setAgent={setAgent}
              collapsed={collapsed}
              toggleSidebar={() => setCollapsed((c) => !c)}
              hasCredential={hasCredential}
              openAuth={openAuth}
              reloadKey={reloadKey}
            />
          }
        >
          <Route index element={<Navigate to="/metrics" replace />} />
          <Route path="/metrics" element={<MetricsScreen />} />
          <Route path="/traces" element={<TracesScreen />} />
          <Route path="/traces/:traceId" element={<TraceDetailScreen />} />
          <Route path="/policies" element={<PoliciesScreen />} />
          <Route path="/keys" element={<KeysScreen />} />
          <Route path="*" element={<Navigate to="/metrics" replace />} />
        </Route>
      </Routes>

      <AuthDialog open={authOpen} prompted={authPrompted} onClose={() => setAuthOpen(false)} />
    </ToastProvider>
  );
}
