import { useState, useEffect } from 'react';
import { Sidebar } from './components/layout/Sidebar';
import { Header } from './components/layout/Header';
import { TracesScreen } from './components/screens/TracesScreen';
import { TraceDetailScreen } from './components/screens/TraceDetailScreen';
import { MetricsScreen } from './components/screens/MetricsScreen';
import { PoliciesScreen } from './components/screens/PoliciesScreen';
import { AuthDialog } from './components/ui/AuthDialog';
import { AGENTS } from './data/mockData';
import { AUTH_REQUIRED_EVENT, TOKEN_CHANGED_EVENT, authBus, getToken } from './lib/auth';

type Route = 'metrics' | 'traces' | 'trace' | 'policies' | 'system';

function App() {
  const [theme, setTheme] = useState<'dark' | 'light'>(
    () => (localStorage.getItem('argox.theme') as 'dark' | 'light') || 'dark'
  );
  const [route, setRoute] = useState<Route>(
    () => (localStorage.getItem('argox.route') as Route) || 'metrics'
  );
  const [timeRange, setTimeRange] = useState('24h');
  const [env, setEnv] = useState('production');
  const [agent, setAgent] = useState('all');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);

  // Authentication state.
  const [authOpen, setAuthOpen] = useState(false);
  const [authError, setAuthError] = useState(false);
  const [hasCredential, setHasCredential] = useState(() => Boolean(getToken()));
  // Bumped on credential change to remount screens and force a refetch.
  const [reloadKey, setReloadKey] = useState(0);

  // Open the key dialog automatically when a request is rejected (401/403).
  // Parallel calls (e.g. the three metrics queries) fire several events at
  // once; only react when the dialog is not already open to avoid churn.
  useEffect(() => {
    const onAuthRequired = () => {
      setAuthOpen((open) => {
        if (!open) setAuthError(true);
        return true;
      });
    };
    authBus.addEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
    return () => authBus.removeEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
  }, []);

  // Keep the header's credential indicator in sync with the stored key,
  // including changes made in another tab.
  useEffect(() => {
    const onTokenChanged = () => setHasCredential(Boolean(getToken()));
    authBus.addEventListener(TOKEN_CHANGED_EVENT, onTokenChanged);
    window.addEventListener('storage', onTokenChanged);
    return () => {
      authBus.removeEventListener(TOKEN_CHANGED_EVENT, onTokenChanged);
      window.removeEventListener('storage', onTokenChanged);
    };
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('argox.theme', theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem('argox.route', route);
  }, [route]);

  const activeNav = route === 'trace' ? 'traces' : route;

  // Header configuration per route
  const getHeaderProps = () => {
    switch (route) {
      case 'metrics':
        return { crumbs: [{ label: 'Metrics' }], showTimeControls: true };
      case 'traces':
        return { crumbs: [{ label: 'Traces' }], showTimeControls: true };
      case 'trace':
        return {
          crumbs: [
            { label: 'Traces', onClick: () => setRoute('traces') },
            { label: selectedTraceId || 'Trace', mono: true }
          ],
          showTimeControls: false
        };
      case 'policies':
        return { crumbs: [{ label: 'Policies' }], showTimeControls: false };
      case 'system':
        return { crumbs: [{ label: 'Design system' }], showTimeControls: false };
      default:
        return { title: 'Argox', showTimeControls: true };
    }
  };

  const renderScreen = () => {
    switch (route) {
      case 'metrics':
        return <MetricsScreen timeRange={timeRange} />;
      case 'traces':
        return (
          <TracesScreen
            timeRange={timeRange}
            agent={agent}
            onOpenTrace={(t) => {
              setSelectedTraceId(t.id);
              setRoute('trace');
            }}
          />
        );
      case 'trace':
        return <TraceDetailScreen traceId={selectedTraceId || undefined} onBack={() => setRoute('traces')} />;
      case 'policies':
        return <PoliciesScreen theme={theme} />;
      case 'system':
        return <div className="p-6 text-text-muted">Design System Screen (Coming soon)</div>;
      default:
        return null;
    }
  };

  return (
    <div className="flex h-full bg-background text-text-primary font-ui">
      <Sidebar
        route={activeNav}
        setRoute={(r) => setRoute(r as Route)}
        collapsed={sidebarCollapsed}
      />
      <div className="flex-1 flex flex-col min-w-0 h-full">
        <Header
          {...getHeaderProps()}
          theme={theme}
          setTheme={setTheme}
          timeRange={timeRange}
          setTimeRange={setTimeRange}
          env={env}
          setEnv={setEnv}
          agent={agent}
          setAgent={setAgent}
          agents={AGENTS}
          onToggleSidebar={() => setSidebarCollapsed(!sidebarCollapsed)}
          onOpenAuth={() => { setAuthError(false); setAuthOpen(true); }}
          hasCredential={hasCredential}
        />
        <main key={reloadKey} className="flex-1 overflow-y-auto min-h-0 bg-background">
          {renderScreen()}
        </main>
      </div>

      <AuthDialog
        open={authOpen}
        authError={authError}
        onClose={() => setAuthOpen(false)}
        onSaved={() => {
          // hasCredential is updated by the TOKEN_CHANGED_EVENT listener.
          setReloadKey((k) => k + 1);
        }}
      />
    </div>
  );
}

export default App;
