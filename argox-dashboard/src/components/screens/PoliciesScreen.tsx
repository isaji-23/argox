// Policies: list + Monaco YAML editor, dry-run validation, version diff, and
// save-as-new-version. These endpoints are called WITHOUT auth in this build.
import { useCallback, useEffect, useRef, useState } from 'react';
import Editor, { DiffEditor } from '@monaco-editor/react';
import {
  api,
  APIError,
  type PolicySummary,
  type PolicyResponse,
  type PolicyValidateResponse,
} from '../../lib/api';
import { Icon } from '../shared/Icon';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { Panel, PanelHeader } from '../ui/Panel';
import { Segmented } from '../ui/Segmented';
import { Select } from '../ui/Select';
import { Skeleton, EmptyState, ErrorState } from '../ui/States';
import { useToast } from '../ui/Toast';

type Status = 'active' | 'draft' | 'archived';

const NEW_POLICY_YAML = `id: new-policy
status: draft
version: 1
rules: []
`;

/** Tracks the document theme so Monaco matches the app. */
function useDocTheme(): 'vs-dark' | 'light' {
  const [t, setT] = useState<'vs-dark' | 'light'>(() => (document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'vs-dark'));
  useEffect(() => {
    const obs = new MutationObserver(() => setT(document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'vs-dark'));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => obs.disconnect();
  }, []);
  return t;
}

export function PoliciesScreen() {
  const monacoTheme = useDocTheme();
  const toast = useToast();

  const [policies, setPolicies] = useState<PolicySummary[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState(false);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [newId, setNewId] = useState('');
  const [yaml, setYaml] = useState('');
  const [baselineYaml, setBaselineYaml] = useState('');
  const [status, setStatus] = useState<Status>('draft');
  const [tab, setTab] = useState('editor');
  const [diffVersion, setDiffVersion] = useState(1);
  const [diffYaml, setDiffYaml] = useState('');

  const [validation, setValidation] = useState<PolicyValidateResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const editorLoadingRef = useRef(false);

  const dirty = yaml !== baselineYaml;

  const loadList = useCallback(() => {
    setListLoading(true);
    setListError(false);
    api
      .listPolicies()
      .then((res) => setPolicies(res.policies))
      .catch(() => setListError(true))
      .finally(() => setListLoading(false));
  }, []);

  useEffect(() => {
    loadList();
  }, [loadList]);

  const openPolicy = useCallback(async (p: PolicySummary) => {
    setIsNew(false);
    setSelectedId(p.id);
    setStatus((p.status as Status) ?? 'draft');
    setValidation(null);
    setTab('editor');
    const version = p.active_version ?? p.latest_version;
    setDiffVersion(Math.max(1, version - 1));
    editorLoadingRef.current = true;
    try {
      const text = await api.getPolicyVersionYaml(p.id, version);
      setYaml(text);
      setBaselineYaml(text);
    } catch {
      setYaml('# failed to load policy YAML\n');
      setBaselineYaml('');
    } finally {
      editorLoadingRef.current = false;
    }
  }, []);

  const startNew = () => {
    setIsNew(true);
    setSelectedId(null);
    setNewId('');
    setStatus('draft');
    setYaml(NEW_POLICY_YAML);
    setBaselineYaml('');
    setValidation(null);
    setTab('editor');
  };

  const validate = async () => {
    setBusy(true);
    try {
      const res = await api.validatePolicy(yaml);
      setValidation(res);
    } catch (e) {
      setValidation({ valid: false, errors: [e instanceof Error ? e.message : 'Validation request failed'] });
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setBusy(true);
    try {
      // Parse rules out of the YAML via the validate endpoint.
      const res = await api.validatePolicy(yaml);
      setValidation(res);
      if (!res.valid || !res.policy) {
        setBusy(false);
        return;
      }
      const rules = (res.policy as PolicyResponse).rules ?? [];
      let saved: PolicyResponse;
      if (isNew) {
        const id = newId.trim() || (res.policy as PolicyResponse).id;
        saved = await api.createPolicy({ id, status, rules });
      } else if (selectedId) {
        saved = await api.updatePolicy(selectedId, { status, rules });
      } else {
        setBusy(false);
        return;
      }
      toast.success(`Saved ${saved.id} v${saved.version}`);
      setBaselineYaml(yaml);
      setIsNew(false);
      setSelectedId(saved.id);
      loadList();
    } catch (e) {
      const msg = e instanceof APIError ? e.message : 'Failed to save policy';
      setValidation({ valid: false, errors: [msg] });
      toast.error(msg);
    } finally {
      setBusy(false);
    }
  };

  // Load the comparison version when entering the Diff tab.
  useEffect(() => {
    if (tab !== 'diff' || !selectedId) return;
    let cancelled = false;
    api
      .getPolicyVersionYaml(selectedId, diffVersion)
      .then((t) => !cancelled && setDiffYaml(t))
      .catch(() => !cancelled && setDiffYaml('# failed to load version\n'));
    return () => {
      cancelled = true;
    };
  }, [tab, selectedId, diffVersion]);

  const current = policies.find((p) => p.id === selectedId);
  const errorCount = validation && !validation.valid ? validation.errors.length : 0;

  return (
    <div className="ax-fade-in" style={{ padding: '18px 22px 28px', height: '100%', display: 'flex', flexDirection: 'column', maxWidth: 1340, margin: '0 auto', width: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: 14 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 'var(--fs-xl)', fontWeight: 600, letterSpacing: '-0.015em' }}>Policies</h1>
          <p style={{ margin: '3px 0 0', fontSize: 'var(--fs-sm)', color: 'var(--text-muted)' }}>
            YAML policies enforced by the Argox gateway · validate and save as a new version
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {dirty && (
            <span style={{ fontSize: 'var(--fs-xs)', color: 'var(--warn)', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <span style={{ width: 6, height: 6, borderRadius: 999, background: 'var(--warn)' }} />
              unsaved
            </span>
          )}
          <Button variant="secondary" size="sm" icon="play" onClick={validate} disabled={busy || (!selectedId && !isNew)}>
            Validate
          </Button>
          <Button variant="primary" size="sm" icon="save" onClick={save} disabled={busy || (!dirty && !isNew) || (!selectedId && !isNew)}>
            Save new version
          </Button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '266px 1fr', gap: 14, flex: 1, minHeight: 0 }}>
        {/* policy list */}
        <Panel pad={false} style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 0 }}>
          <div style={{ padding: '11px 14px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <PanelHeader title="Policies" icon="policies" />
            <Button variant="accentSoft" size="sm" icon="plus" onClick={startNew}>
              New
            </Button>
          </div>
          <div style={{ overflowY: 'auto', flex: 1 }}>
            {listLoading ? (
              <div style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
                {[0, 1, 2].map((i) => <Skeleton key={i} h={40} r={8} />)}
              </div>
            ) : listError ? (
              <ErrorState title="Failed to load policies" onRetry={loadList} />
            ) : policies.length === 0 && !isNew ? (
              <EmptyState icon="policies" title="No policies yet" body="Create one to start enforcing rules." />
            ) : (
              <>
                {isNew && (
                  <div style={{ padding: '11px 14px', borderBottom: '1px solid var(--border-faint)', background: 'var(--accent-surface)', borderLeft: '2.5px solid var(--accent)' }}>
                    <div style={{ fontSize: 'var(--fs-sm)', fontWeight: 600, color: 'var(--accent)' }}>New policy</div>
                    <div style={{ fontSize: 'var(--fs-2xs)', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>unsaved draft</div>
                  </div>
                )}
                {policies.map((p) => {
                  const sel = p.id === selectedId;
                  return (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => openPolicy(p)}
                      style={{
                        display: 'block',
                        width: '100%',
                        textAlign: 'left',
                        padding: '11px 14px',
                        borderBottom: '1px solid var(--border-faint)',
                        background: sel ? 'var(--accent-surface)' : 'transparent',
                        border: 'none',
                        borderLeftWidth: '2.5px',
                        borderLeftStyle: 'solid',
                        borderLeftColor: sel ? 'var(--accent)' : 'transparent',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-sm)', fontWeight: 600, color: sel ? 'var(--accent)' : 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {p.id}
                        </span>
                        <span style={{ flex: 1 }} />
                        <Badge tone={p.status === 'active' ? 'allow' : p.status === 'archived' ? 'neutral' : 'warn'}>{p.status}</Badge>
                      </div>
                      <div style={{ fontSize: 'var(--fs-2xs)', color: 'var(--text-faint)', fontFamily: 'var(--font-mono)' }}>
                        latest v{p.latest_version}
                        {p.active_version != null ? ` · active v${p.active_version}` : ''}
                      </div>
                    </button>
                  );
                })}
              </>
            )}
          </div>
        </Panel>

        {/* editor workspace */}
        <div style={{ display: 'flex', flexDirection: 'column', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', overflow: 'hidden', minHeight: 0, background: 'var(--bg-surface)' }}>
          {!selectedId && !isNew ? (
            <EmptyState icon="policies" title="Select a policy" body="Choose a policy on the left, or create a new one." />
          ) : (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 12px', borderBottom: '1px solid var(--border)', background: 'var(--bg-surface-2)', flexWrap: 'wrap' }}>
                <Segmented
                  size="sm"
                  value={tab}
                  onChange={setTab}
                  options={[
                    { value: 'editor', label: 'Editor', icon: 'policies' },
                    { value: 'diff', label: 'Diff', icon: 'diff' },
                  ]}
                />
                {isNew ? (
                  <input
                    value={newId}
                    onChange={(e) => setNewId(e.target.value)}
                    placeholder="policy-id"
                    style={{
                      background: 'var(--bg-surface-3)',
                      border: '1px solid var(--border-strong)',
                      borderRadius: 'var(--r-sm)',
                      padding: '4px 9px',
                      color: 'var(--text-primary)',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 'var(--fs-sm)',
                      outline: 'none',
                      width: 160,
                    }}
                  />
                ) : (
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-xs)', color: 'var(--text-muted)' }}>{selectedId}</span>
                )}

                <div style={{ width: 130 }}>
                  <Select
                    value={status}
                    onChange={(v) => setStatus(v as Status)}
                    minWidth={130}
                    size="sm"
                    options={[
                      { value: 'draft', label: 'draft' },
                      { value: 'active', label: 'active' },
                      { value: 'archived', label: 'archived' },
                    ]}
                  />
                </div>

                {tab === 'diff' && current && current.latest_version > 1 && (
                  <Select
                    size="sm"
                    value={String(diffVersion)}
                    onChange={(v) => setDiffVersion(Number(v))}
                    minWidth={120}
                    options={Array.from({ length: current.latest_version }, (_, i) => ({ value: String(i + 1), label: `Compare v${i + 1}` }))}
                  />
                )}

                <span style={{ flex: 1 }} />
                {validation && (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 'var(--fs-xs)', color: validation.valid ? 'var(--allow)' : 'var(--block-bright)', fontFamily: 'var(--font-mono)' }}>
                    <Icon name={validation.valid ? 'check' : 'ban'} size={13} />
                    {validation.valid ? `${(validation.policy as PolicyResponse | undefined)?.rules?.length ?? 0} rules · valid` : `${errorCount} errors`}
                  </span>
                )}
              </div>

              <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
                {tab === 'editor' ? (
                  <Editor
                    height="100%"
                    language="yaml"
                    theme={monacoTheme}
                    value={yaml}
                    onChange={(v) => setYaml(v ?? '')}
                    options={{
                      fontFamily: 'var(--font-mono), monospace',
                      fontSize: 12.5,
                      minimap: { enabled: false },
                      scrollBeyondLastLine: false,
                      tabSize: 2,
                      lineNumbersMinChars: 3,
                      padding: { top: 10 },
                    }}
                  />
                ) : (
                  <DiffEditor
                    height="100%"
                    language="yaml"
                    theme={monacoTheme}
                    original={diffYaml}
                    modified={yaml}
                    options={{ readOnly: true, renderSideBySide: true, minimap: { enabled: false }, fontSize: 12.5, scrollBeyondLastLine: false }}
                  />
                )}
              </div>

              {/* validation result bar */}
              {validation && tab === 'editor' && (
                <div
                  className="ax-fade-in"
                  style={{
                    padding: '10px 14px',
                    borderTop: '1px solid var(--border)',
                    background: validation.valid ? 'var(--allow-surface)' : 'var(--block-bg)',
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 11,
                  }}
                >
                  <span style={{ color: validation.valid ? 'var(--allow)' : 'var(--block-bright)', display: 'flex', marginTop: 1 }}>
                    <Icon name={validation.valid ? 'check' : 'ban'} size={16} strokeWidth={2} />
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 'var(--fs-sm)', fontWeight: 600, color: validation.valid ? 'var(--allow-bright)' : 'var(--block-ink)' }}>
                      {validation.valid ? 'Validation passed — schema valid, not persisted' : 'Validation failed — fix errors before saving'}
                    </div>
                    {!validation.valid && (
                      <ul style={{ margin: '4px 0 0', padding: '0 0 0 16px', fontSize: 'var(--fs-xs)', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
                        {validation.errors.map((err, i) => (
                          <li key={i}>{err}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <button type="button" onClick={() => setValidation(null)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', display: 'flex' }}>
                    <Icon name="x" size={15} />
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>

    </div>
  );
}
