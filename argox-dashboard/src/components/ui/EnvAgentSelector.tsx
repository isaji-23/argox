import { Select } from '../ui/Select';

interface EnvAgentSelectorProps {
  env: string;
  setEnv: (env: string) => void;
  agent: string;
  setAgent: (agent: string) => void;
  agents: string[];
}

export function EnvAgentSelector({ env, setEnv, agent, setAgent, agents }: EnvAgentSelectorProps) {
  const agentOptions = [
    { value: 'all', label: 'All agents' },
    ...agents.map((a) => ({ value: a, label: a }))
  ];

  return (
    <div className="flex items-center gap-px bg-surface-3 border border-border-strong rounded-md overflow-hidden">
      <div className="border-r border-border">
        <Select
          value={env}
          onChange={setEnv}
          icon="database"
          minWidth={110}
          size="sm"
          options={['production', 'staging', 'dev']}
          className="border-none rounded-none"
        />
      </div>
      <Select
        value={agent}
        onChange={setAgent}
        icon="bolt"
        minWidth={140}
        size="sm"
        options={agentOptions}
        className="border-none rounded-none"
      />
    </div>
  );
}
