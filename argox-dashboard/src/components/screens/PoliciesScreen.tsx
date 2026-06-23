import { useState, useEffect } from 'react';
import Editor, { DiffEditor } from '@monaco-editor/react';
import { api } from '../../lib/api';
import type { PolicySummary } from '../../lib/api';
import { Icon } from '../shared/Icon';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { Skeleton, ErrorState } from '../ui/States';

interface PoliciesScreenProps {
  theme?: 'dark' | 'light';
}

const DEFAULT_SKELETON = `# argox policy
apiVersion: argox.dev/v1
kind: PolicyBundle
metadata:
  agent: billing-copilot
  env: production

id: billing-copilot
status: draft
version: 1

rules:
  - id: finance.refund.max_amount
    trigger: refund_issue
    condition:
      metric: arg.amount
      operator: gt
      threshold: 500.00
    action: block
    reason: Refunds over $500 require a finance approval token.
`;

export function PoliciesScreen({ theme = 'dark' }: PoliciesScreenProps) {
  const [policies, setPolicies] = useState<PolicySummary[]>([]);
  const [selectedPolicyId, setSelectedPolicyId] = useState<string | null>(null);
  
  // Active document states
  const [currentYaml, setCurrentYaml] = useState<string>('');
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [selectedStatus, setSelectedStatus] = useState<'active' | 'draft' | 'archived'>('draft');

  // Loading/saving/validation states
  const [loadingList, setLoadingList] = useState<boolean>(true);
  const [loadingDetail, setLoadingDetail] = useState<boolean>(false);
  const [saving, setSaving] = useState<boolean>(false);
  const [validating, setValidating] = useState<boolean>(false);
  const [validationResult, setValidationResult] = useState<{
    valid: boolean;
    errors: string[];
    policy?: any;
  } | null>(null);
  
  // UI States
  const [error, setError] = useState<string | null>(null);
  const [currentTab, setCurrentTab] = useState<'edit' | 'diff'>('edit');
  const [isCreatingNew, setIsCreatingNew] = useState<boolean>(false);

  // Diff comparison states
  const [diffVersionA, setDiffVersionA] = useState<number | ''>('');
  const [diffVersionB, setDiffVersionB] = useState<number | ''>('');
  const [diffYamlA, setDiffYamlA] = useState<string>('');
  const [diffYamlB, setDiffYamlB] = useState<string>('');
  const [loadingDiff, setLoadingDiff] = useState<boolean>(false);

  // Fetch policies on mount
  const fetchPolicies = async (selectId?: string) => {
    try {
      setLoadingList(true);
      const res = await api.listPolicies();
      setPolicies(res.policies);
      
      // Select default policy if available
      if (res.policies.length > 0) {
        const idToSelect = selectId || res.policies[0].id;
        setSelectedPolicyId(idToSelect);
        setIsCreatingNew(false);
      } else {
        setSelectedPolicyId(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch policies list');
    } finally {
      setLoadingList(false);
    }
  };

  useEffect(() => {
    fetchPolicies();
  }, []);

  // Fetch policy detail when selection changes
  const loadPolicyDetail = async (id: string, version?: number) => {
    try {
      setLoadingDetail(true);
      setError(null);
      setValidationResult(null);
      
      const summary = policies.find(p => p.id === id);
      if (!summary) return;

      const verToLoad = version !== undefined ? version : (summary.active_version || summary.latest_version);
      setSelectedVersion(verToLoad);
      setSelectedStatus(summary.status);

      // Load raw YAML
      const yaml = await api.getPolicyVersionYaml(id, verToLoad);
      setCurrentYaml(yaml);

      // Reset diff selections
      setDiffVersionB(verToLoad);
      setDiffVersionA(verToLoad > 1 ? verToLoad - 1 : verToLoad);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load policy details');
    } finally {
      setLoadingDetail(false);
    }
  };

  useEffect(() => {
    if (selectedPolicyId && !isCreatingNew) {
      loadPolicyDetail(selectedPolicyId);
    }
  }, [selectedPolicyId, policies, isCreatingNew]);

  // Load diff YAMLs
  const loadDiffYamls = async () => {
    if (!selectedPolicyId || diffVersionA === '' || diffVersionB === '') return;
    try {
      setLoadingDiff(true);
      const [yamlA, yamlB] = await Promise.all([
        api.getPolicyVersionYaml(selectedPolicyId, Number(diffVersionA)),
        api.getPolicyVersionYaml(selectedPolicyId, Number(diffVersionB))
      ]);
      setDiffYamlA(yamlA);
      setDiffYamlB(yamlB);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load policy versions for diff');
    } finally {
      setLoadingDiff(false);
    }
  };

  useEffect(() => {
    if (currentTab === 'diff' && selectedPolicyId) {
      loadDiffYamls();
    }
  }, [currentTab, diffVersionA, diffVersionB, selectedPolicyId]);

  // Dry-run validate policy
  const handleValidate = async () => {
    setValidating(true);
    setValidationResult(null);
    try {
      const res = await api.validatePolicy(currentYaml);
      setValidationResult(res);
    } catch (err) {
      setValidationResult({
        valid: false,
        errors: [err instanceof Error ? err.message : 'Failed to validate policy']
      });
    } finally {
      setValidating(false);
    }
  };

  // Save policy version
  const handleSave = async () => {
    setSaving(true);
    try {
      // 1. Dry run validate first
      const valRes = await api.validatePolicy(currentYaml);
      if (!valRes.valid) {
        setValidationResult(valRes);
        throw new Error('Policy validation failed. Please fix errors before saving.');
      }

      const parsedPolicy = valRes.policy;
      if (!parsedPolicy) {
        throw new Error('Validation succeeded but did not return the parsed policy details.');
      }

      if (isCreatingNew) {
        // Create new policy
        const payload = {
          id: parsedPolicy.id,
          status: selectedStatus,
          rules: parsedPolicy.rules,
          created_by: parsedPolicy.created_by || 'dashboard'
        };
        await api.createPolicy(payload);
        setIsCreatingNew(false);
        await fetchPolicies(parsedPolicy.id);
      } else if (selectedPolicyId) {
        // Update existing policy (creates version n+1)
        const payload = {
          status: selectedStatus,
          rules: parsedPolicy.rules,
          created_by: parsedPolicy.created_by || 'dashboard'
        };
        await api.updatePolicy(selectedPolicyId, payload);
        await fetchPolicies(selectedPolicyId);
      }
      
      setValidationResult({ valid: true, errors: [] });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save policy');
    } finally {
      setSaving(false);
    }
  };

  // Start new policy creation
  const handleInitCreateNew = () => {
    setIsCreatingNew(true);
    setSelectedPolicyId(null);
    setCurrentYaml(DEFAULT_SKELETON);
    setSelectedVersion(1);
    setSelectedStatus('draft');
    setValidationResult(null);
    setCurrentTab('edit');
  };

  const selectedPolicySummary = policies.find(p => p.id === selectedPolicyId);

  return (
    <div className="flex h-full min-w-0 bg-background text-text-primary font-ui">
      {/* LEFT SIDEBAR - Policy List */}
      <div className="w-80 flex-shrink-0 border-r border-border bg-surface flex flex-col min-h-0">
        <div className="p-4 border-b border-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Icon name="policies" className="text-accent" size={18} />
            <h2 className="text-md font-bold font-display">Governance Policies</h2>
          </div>
          <Button
            variant="accentSoft"
            size="sm"
            icon="plus"
            onClick={handleInitCreateNew}
            disabled={isCreatingNew}
          >
            New
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-2">
          {loadingList ? (
            <div className="flex flex-col gap-3 p-2">
              <Skeleton h={36} />
              <Skeleton h={36} />
              <Skeleton h={36} />
            </div>
          ) : policies.length === 0 ? (
            <div className="text-center p-6 text-text-muted text-sm">
              No policies found. Click 'New' to create one.
            </div>
          ) : (
            policies.map((p) => {
              const isSelected = p.id === selectedPolicyId;
              const statusTone = p.status === 'active' ? 'allow' : p.status === 'draft' ? 'gold' : 'neutral';
              
              return (
                <button
                  key={p.id}
                  onClick={() => {
                    setIsCreatingNew(false);
                    setSelectedPolicyId(p.id);
                  }}
                  className={`w-full text-left p-3 rounded-md border transition-all flex flex-col gap-1.5 ${
                    isSelected
                      ? 'bg-surface-3 border-accent text-text-primary shadow-sm'
                      : 'bg-surface-2 border-border-soft hover:border-border hover:bg-surface-3 text-text-secondary'
                  }`}
                >
                  <div className="flex items-center justify-between w-full">
                    <span className="font-semibold font-mono text-sm truncate max-w-[170px]" title={p.id}>
                      {p.id}
                    </span>
                    <Badge tone={statusTone}>{p.status}</Badge>
                  </div>
                  
                  <div className="flex items-center justify-between text-xs text-text-muted">
                    <span>Latest: v{p.latest_version}</span>
                    {p.active_version ? (
                      <span className="flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-allow" />
                        v{p.active_version} active
                      </span>
                    ) : (
                      <span>Inactive</span>
                    )}
                  </div>
                </button>
              );
            })
          )}
        </div>
      </div>

      {/* RIGHT WORKSPACE - Monaco Editor & Control panel */}
      <div className="flex-1 flex flex-col min-h-0 bg-background min-w-0">
        {loadingDetail ? (
          <div className="flex-1 flex flex-col justify-center items-center gap-4">
            <Skeleton w="60%" h={40} />
            <Skeleton w="90%" h="50vh" />
          </div>
        ) : error && !selectedPolicyId && !isCreatingNew ? (
          <div className="flex-1 flex justify-center items-center">
            <ErrorState
              title="Failed to load policies"
              body={error}
              onRetry={() => fetchPolicies(selectedPolicyId || undefined)}
            />
          </div>
        ) : !selectedPolicyId && !isCreatingNew ? (
          <div className="flex-1 flex flex-col justify-center items-center text-center p-12">
            <div className="w-16 h-16 rounded-xl bg-surface-2 border border-border flex items-center justify-center text-text-muted mb-4 shadow-md">
              <Icon name="policies" size={28} />
            </div>
            <h3 className="text-lg font-bold font-display text-text-primary mb-2">No Policy Selected</h3>
            <p className="text-text-muted text-sm max-w-sm mb-6">
              Select a policy from the sidebar to inspect its rules and configuration, or create a brand new one.
            </p>
            <Button variant="primary" icon="plus" onClick={handleInitCreateNew}>
              Create Policy Bundle
            </Button>
          </div>
        ) : (
          <div className="flex-1 flex flex-col min-h-0 min-w-0">
            {/* WORKSPACE HEADER */}
            <div className="px-6 py-4 border-b border-border bg-surface flex flex-wrap items-center justify-between gap-4">
              <div className="flex flex-col gap-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-lg font-mono text-text-primary truncate">
                    {isCreatingNew ? 'new-policy' : selectedPolicyId}
                  </span>
                  {!isCreatingNew && selectedVersion && (
                    <Badge tone="neutral" className="font-mono">
                      v{selectedVersion}
                    </Badge>
                  )}
                  {isCreatingNew && <Badge tone="gold">New Draft</Badge>}
                </div>
                <div className="flex items-center gap-2 text-xs text-text-muted">
                  <span>Status:</span>
                  <select
                    value={selectedStatus}
                    onChange={(e) => setSelectedStatus(e.target.value as any)}
                    className="bg-surface-3 border border-border rounded px-1.5 py-0.5 text-text-primary text-xs font-semibold focus:outline-none focus:border-accent"
                  >
                    <option value="draft">Draft</option>
                    <option value="active">Active</option>
                    <option value="archived">Archived</option>
                  </select>

                  {!isCreatingNew && selectedPolicySummary && selectedPolicySummary.latest_version > 1 && (
                    <>
                      <span className="mx-1">•</span>
                      <span>View Version:</span>
                      <select
                        value={selectedVersion || ''}
                        onChange={(e) => loadPolicyDetail(selectedPolicyId!, Number(e.target.value))}
                        className="bg-surface-3 border border-border rounded px-1.5 py-0.5 text-text-primary text-xs font-mono focus:outline-none focus:border-accent"
                      >
                        {Array.from({ length: selectedPolicySummary.latest_version }, (_, i) => i + 1)
                          .reverse()
                          .map(v => (
                            <option key={v} value={v}>v{v} {v === selectedPolicySummary.active_version ? '(Active)' : ''}</option>
                          ))
                        }
                      </select>
                    </>
                  )}
                </div>
              </div>

              {/* TABS */}
              {!isCreatingNew && (
                <div className="flex rounded-lg bg-surface-2 p-1 border border-border-soft">
                  <button
                    onClick={() => setCurrentTab('edit')}
                    className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-all flex items-center gap-1.5 ${
                      currentTab === 'edit'
                        ? 'bg-surface-3 border border-border text-text-primary shadow-sm'
                        : 'text-text-secondary hover:text-text-primary'
                    }`}
                  >
                    <Icon name="eye" size={13} />
                    Editor
                  </button>
                  <button
                    onClick={() => setCurrentTab('diff')}
                    className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-all flex items-center gap-1.5 ${
                      currentTab === 'diff'
                        ? 'bg-surface-3 border border-border text-text-primary shadow-sm'
                        : 'text-text-secondary hover:text-text-primary'
                    }`}
                  >
                    <Icon name="diff" size={13} />
                    Diff History
                  </button>
                </div>
              )}

              {/* ACTION BUTTONS */}
              <div className="flex items-center gap-2">
                {currentTab === 'edit' && (
                  <>
                    <Button
                      variant="outline"
                      size="sm"
                      icon="play"
                      onClick={handleValidate}
                      disabled={validating}
                    >
                      {validating ? 'Validating...' : 'Validate Schema'}
                    </Button>
                    <Button
                      variant="primary"
                      size="sm"
                      icon="save"
                      onClick={handleSave}
                      disabled={saving}
                    >
                      {saving ? 'Saving...' : 'Save Version'}
                    </Button>
                  </>
                )}
                {isCreatingNew && (
                  <Button variant="ghost" size="sm" onClick={() => fetchPolicies()}>
                    Cancel
                  </Button>
                )}
              </div>
            </div>

            {/* ERROR DISPLAY */}
            {error && (
              <div className="bg-block-bg border-b border-block-border text-block-bright px-6 py-3 text-xs font-mono flex items-center justify-between gap-4 animate-ax-shimmer">
                <div className="flex items-center gap-2">
                  <Icon name="warn" size={14} />
                  <span>{error}</span>
                </div>
                <button onClick={() => setError(null)} className="text-text-muted hover:text-text-primary">
                  <Icon name="x" size={14} />
                </button>
              </div>
            )}

            {/* WORKSPACE CONTENT */}
            <div className="flex-1 flex flex-col min-h-0 min-w-0">
              {currentTab === 'edit' ? (
                <div className="flex-1 flex flex-col min-h-0 relative min-w-0">
                  <div className="flex-1 min-h-0 relative border-b border-border bg-background">
                    <Editor
                      height="100%"
                      defaultLanguage="yaml"
                      language="yaml"
                      theme={theme === 'dark' ? 'vs-dark' : 'light'}
                      value={currentYaml}
                      onChange={(val) => {
                        setCurrentYaml(val || '');
                        if (validationResult) setValidationResult(null);
                      }}
                      options={{
                        minimap: { enabled: false },
                        fontSize: 13,
                        lineNumbers: 'on',
                        scrollBeyondLastLine: false,
                        automaticLayout: true,
                        tabSize: 2,
                        wordWrap: 'on'
                      }}
                    />
                  </div>

                  {/* BOTTOM VALIDATION BAR */}
                  <div className="h-44 flex-shrink-0 bg-surface flex flex-col border-t border-border">
                    <div className="px-4 py-2 border-b border-border bg-surface-2 flex items-center justify-between">
                      <span className="text-xs font-bold font-display uppercase tracking-wider text-text-secondary">
                        Dry-Run Schema Validation
                      </span>
                      {validationResult ? (
                        validationResult.valid ? (
                          <span className="text-xs font-semibold text-allow flex items-center gap-1.5">
                            <Icon name="check" size={14} />
                            Policy schema is valid
                          </span>
                        ) : (
                          <span className="text-xs font-semibold text-block-bright flex items-center gap-1.5">
                            <Icon name="warn" size={14} />
                            Schema violations ({validationResult.errors.length})
                          </span>
                        )
                      ) : (
                        <span className="text-xs text-text-muted">Not validated yet</span>
                      )}
                    </div>
                    <div className="flex-1 p-4 overflow-y-auto font-mono text-xs text-text-secondary bg-surface">
                      {validationResult ? (
                        validationResult.valid ? (
                          <div className="flex flex-col gap-2">
                            <div className="text-allow">✓ OK: All policy rules parsed and validated against the Pydantic schema model successfully.</div>
                            <div className="text-text-muted mt-1">
                              Ready to be deployed. Rules parsed: {validationResult.policy?.rules?.length || 0}.
                            </div>
                          </div>
                        ) : (
                          <div className="flex flex-col gap-1.5 text-block-bright">
                            <div className="font-semibold mb-1">Validation Errors:</div>
                            {validationResult.errors.map((err, i) => (
                              <div key={i} className="flex gap-2 items-start pl-2 border-l-2 border-block">
                                <span className="text-block">•</span>
                                <span className="break-all">{err}</span>
                              </div>
                            ))}
                          </div>
                        )
                      ) : (
                        <div className="text-text-muted flex flex-col justify-center items-center h-full gap-2">
                          <Icon name="bolt" size={16} />
                          <span>Make edits in the editor and click "Validate Schema" to verify rule logic.</span>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ) : (
                /* DIFF TAB */
                <div className="flex-1 flex flex-col min-h-0 min-w-0">
                  {/* DIFF CONTROLS */}
                  <div className="px-6 py-3 bg-surface-2 border-b border-border flex items-center gap-4 text-sm text-text-secondary flex-wrap">
                    <span className="font-semibold text-text-primary">Compare Versions:</span>
                    
                    <div className="flex items-center gap-2">
                      <span>Left Side:</span>
                      <select
                        value={diffVersionA}
                        onChange={(e) => setDiffVersionA(Number(e.target.value))}
                        className="bg-surface-3 border border-border rounded px-2 py-1 text-text-primary text-xs font-mono focus:outline-none focus:border-accent"
                      >
                        {selectedPolicySummary && Array.from({ length: selectedPolicySummary.latest_version }, (_, i) => i + 1).map(v => (
                          <option key={v} value={v}>v{v} {v === selectedPolicySummary.active_version ? '(Active)' : ''}</option>
                        ))}
                      </select>
                    </div>

                    <Icon name="arrowRight" className="text-text-muted" size={14} />

                    <div className="flex items-center gap-2">
                      <span>Right Side:</span>
                      <select
                        value={diffVersionB}
                        onChange={(e) => setDiffVersionB(Number(e.target.value))}
                        className="bg-surface-3 border border-border rounded px-2 py-1 text-text-primary text-xs font-mono focus:outline-none focus:border-accent"
                      >
                        {selectedPolicySummary && Array.from({ length: selectedPolicySummary.latest_version }, (_, i) => i + 1).map(v => (
                          <option key={v} value={v}>v{v} {v === selectedPolicySummary.active_version ? '(Active)' : ''}</option>
                        ))}
                      </select>
                    </div>

                    {loadingDiff && (
                      <span className="text-xs text-text-muted flex items-center gap-1.5 ml-auto">
                        <span className="w-3 h-3 border-2 border-text-muted border-t-transparent rounded-full animate-spin" />
                        Loading versions...
                      </span>
                    )}
                  </div>

                  {/* DIFF EDITOR CONTAINER */}
                  <div className="flex-1 min-h-0 relative min-w-0 bg-background">
                    <DiffEditor
                      height="100%"
                      original={diffYamlA}
                      modified={diffYamlB}
                      language="yaml"
                      theme={theme === 'dark' ? 'vs-dark' : 'light'}
                      options={{
                        readOnly: true,
                        minimap: { enabled: false },
                        fontSize: 13,
                        automaticLayout: true,
                        renderSideBySide: true
                      }}
                    />
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
