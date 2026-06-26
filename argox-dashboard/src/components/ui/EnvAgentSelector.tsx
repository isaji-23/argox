// Combined environment + agent selector (two joined Selects).
// Deliberately NOT wrapped in an `overflow-hidden` container so the portal
// menus position correctly (FRONTEND_SPEC §5).
import { Select, type SelectOption } from './Select';

interface EnvAgentSelectorProps {
  env: string;
  setEnv: (v: string) => void;
  agent: string;
  setAgent: (v: string) => void;
  agents?: string[];
}

const ENV_OPTIONS: SelectOption[] = [
  { value: 'production', label: 'production' },
  { value: 'staging', label: 'staging' },
  { value: 'dev', label: 'dev' },
];

export function EnvAgentSelector({ env, setEnv, agent, setAgent, agents = [] }: EnvAgentSelectorProps) {
  const agentOptions: SelectOption[] = [
    { value: 'all', label: 'All agents' },
    ...agents.map((a) => ({ value: a, label: a })),
  ];
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        background: 'var(--bg-surface-3)',
        border: '1px solid var(--border-strong)',
        borderRadius: 'var(--r-md)',
      }}
    >
      <div style={{ borderRight: '1px solid var(--border)' }}>
        <Select value={env} onChange={setEnv} icon="database" minWidth={120} size="sm" options={ENV_OPTIONS} />
      </div>
      <Select value={agent} onChange={setAgent} icon="bolt" minWidth={150} size="sm" options={agentOptions} />
    </div>
  );
}
