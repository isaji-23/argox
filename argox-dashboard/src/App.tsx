import { useState, useEffect } from 'react';
import { Sidebar } from './components/layout/Sidebar';
import { Header } from './components/layout/Header';
import { TracesScreen } from './components/screens/TracesScreen';
import { AGENTS, FEATURED_TRACE } from './data/mockData';

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
            { label: FEATURED_TRACE.id, mono: true }
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
        return <div className="p-6 text-text-muted">Metrics Screen (Coming soon)</div>;
      case 'traces':
        return (
          <TracesScreen
            timeRange={timeRange}
            agent={agent}
            onOpenTrace={(t) => {
              console.log('Open trace', t);
              setRoute('trace');
            }}
          />
        );
      case 'trace':
        return <div className="p-6 text-text-muted">Trace Detail Screen (Coming soon)</div>;
      case 'policies':
        return <div className="p-6 text-text-muted">Policies Screen (Coming soon)</div>;
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
        />
        <main className="flex-1 overflow-y-auto min-h-0 bg-background">
          {renderScreen()}
        </main>
      </div>
    </div>
  );
}

export default App;
