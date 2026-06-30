// API Keys: admin-scoped CRUD over the Collector key store. Uses the admin
// credential slot (separate from the read key) via `adminFetch`.
import { useCallback, useEffect, useState } from 'react';
import {
  api,
  APIError,
  type ApiKeyView,
  type ApiKeyCreateResponse,
  type KeyScope,
} from '../../lib/api';
import {
  authBus,
  getAdminToken,
  setAdminToken,
  clearAdminToken,
  ADMIN_TOKEN_CHANGED_EVENT,
} from '../../lib/auth';
import { Icon } from '../shared/Icon';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { Panel, PanelHeader, SectionLabel } from '../ui/Panel';
import { Select } from '../ui/Select';
import { Skeleton, EmptyState, ErrorState } from '../ui/States';
import { useToast } from '../ui/Toast';

const SCOPES: KeyScope[] = ['read', 'ingest', 'policy-read', 'policy-write', 'admin'];

const EXPIRY_OPTIONS = [
  { value: 'never', label: 'Never', seconds: undefined as number | undefined },
  { value: '30d', label: '30 days', seconds: 30 * 86400 },
  { value: '90d', label: '90 days', seconds: 90 * 86400 },
  { value: '1y', label: '1 year', seconds: 365 * 86400 },
];

function keyStatus(k: ApiKeyView): { label: string; tone: 'allow' | 'warn' | 'block' | 'neutral' } {
  if (k.revoked || k.revoked_at) return { label: 'revoked', tone: 'block' };
  if (k.expires_at && new Date(k.expires_at).getTime() < Date.now()) return { label: 'expired', tone: 'warn' };
  return { label: 'active', tone: 'allow' };
}

export function KeysScreen() {
  const toast = useToast();
  const [adminInput, setAdminInput] = useState(getAdminToken() ?? '');
  const [reveal, setReveal] = useState(false);
  const [hasAdmin, setHasAdmin] = useState(!!getAdminToken());

  const [keys, setKeys] = useState<ApiKeyView[]>([]);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);

  const [name, setName] = useState('');
  const [scopes, setScopes] = useState<KeyScope[]>(['read']);
  const [expiryIdx, setExpiryIdx] = useState('never');
  const [createError, setCreateError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newSecret, setNewSecret] = useState<ApiKeyCreateResponse | null>(null);
  const [copied, setCopied] = useState(false);

  const loadKeys = useCallback(() => {
    if (!getAdminToken()) {
      setKeys([]);
      return;
    }
    setLoading(true);
    setListError(null);
    api
      .listKeys()
      .then((res) => setKeys(res.keys))
      .catch((e) => setListError(e instanceof APIError ? e.message : 'Failed to list keys'))
      .finally(() => setLoading(false));
  }, []);

  // Refetch whenever the admin key changes (also cross-tab).
  useEffect(() => {
    const onChange = () => {
      setHasAdmin(!!getAdminToken());
      loadKeys();
    };
    authBus.addEventListener(ADMIN_TOKEN_CHANGED_EVENT, onChange);
    return () => authBus.removeEventListener(ADMIN_TOKEN_CHANGED_EVENT, onChange);
  }, [loadKeys]);

  useEffect(() => {
    loadKeys();
  }, [loadKeys]);

  const saveAdmin = () => {
    if (!setAdminToken(adminInput)) {
      setListError('Invalid key: contains control characters.');
      return;
    }
    setListError(null);
    toast.success('Admin credential saved');
  };
  const removeAdmin = () => {
    clearAdminToken();
    setAdminInput('');
    toast.info('Admin credential removed');
  };

  const toggleScope = (s: KeyScope) => {
    setScopes((cur) => (cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]));
  };

  const create = async () => {
    if (scopes.length === 0) {
      setCreateError('Select at least one scope.');
      return;
    }
    setCreating(true);
    setCreateError(null);
    setNewSecret(null);
    const expiry = EXPIRY_OPTIONS.find((o) => o.value === expiryIdx);
    const keyName = name.trim() || 'unnamed-key';
    try {
      const res = await api.createKey({
        name: keyName,
        scopes,
        ...(expiry?.seconds ? { expires_in: expiry.seconds } : {}),
      });
      setNewSecret(res);
      setName('');
      setScopes(['read']);
      setExpiryIdx('never');
      loadKeys();
      toast.success(`Key “${keyName}” created`);
    } catch (e) {
      const msg = e instanceof APIError ? e.message : 'Failed to create key';
      setCreateError(msg);
      toast.error(msg);
    } finally {
      setCreating(false);
    }
  };

  const revoke = async (id: string) => {
    try {
      await api.revokeKey(id);
      loadKeys();
      toast.success('Key revoked');
    } catch (e) {
      const msg = e instanceof APIError ? e.message : 'Failed to revoke key';
      setListError(msg);
      toast.error(msg);
    }
  };

  const copySecret = () => {
    if (!newSecret) return;
    navigator.clipboard?.writeText(newSecret.key).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
        toast.success('API key copied to clipboard');
      },
      () => {
        const msg = 'Clipboard unavailable (insecure origin) — copy the key manually.';
        setCreateError(msg);
        toast.error(msg);
      },
    );
  };

  return (
    <div className="ax-fade-in" style={{ padding: '18px 22px 40px', maxWidth: 1100, margin: '0 auto' }}>
      <div style={{ marginBottom: 16 }}>
        <h1 style={{ margin: 0, fontSize: 'var(--fs-xl)', fontWeight: 600, letterSpacing: '-0.015em' }}>API keys</h1>
        <p style={{ margin: '3px 0 0', fontSize: 'var(--fs-sm)', color: 'var(--text-muted)' }}>
          Admin-scoped management of Collector API keys. Requires an admin credential.
        </p>
      </div>

      {/* Admin credential */}
      <Panel style={{ marginBottom: 14 }}>
        <PanelHeader title="Admin credential" subtitle="Any admin-scoped key (including the bootstrap key) works." icon="keys" />
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 14, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 11px', background: 'var(--bg-surface-3)', border: '1px solid var(--border-strong)', borderRadius: 'var(--r-md)', flex: 1, minWidth: 240 }}>
            <Icon name="keys" size={14} style={{ color: 'var(--text-muted)' }} />
            <input
              type={reveal ? 'text' : 'password'}
              value={adminInput}
              onChange={(e) => setAdminInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && saveAdmin()}
              placeholder="argox_admin_…"
              style={{ flex: 1, minWidth: 0, background: 'transparent', border: 'none', outline: 'none', color: 'var(--text-primary)', fontSize: 'var(--fs-sm)', fontFamily: 'var(--font-mono)' }}
            />
            <button type="button" onClick={() => setReveal((r) => !r)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', display: 'flex', padding: 0 }}>
              <Icon name={reveal ? 'eyeOff' : 'eye'} size={15} />
            </button>
          </div>
          <Button variant="primary" size="md" icon="check" onClick={saveAdmin}>
            Save
          </Button>
          {hasAdmin && (
            <Button variant="ghost" size="md" icon="trash" onClick={removeAdmin}>
              Remove
            </Button>
          )}
        </div>
      </Panel>

      {/* One-time secret banner */}
      {newSecret && (
        <Panel style={{ marginBottom: 14, borderColor: 'var(--allow-border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 10 }}>
            <span style={{ color: 'var(--allow)', display: 'flex' }}>
              <Icon name="check" size={16} strokeWidth={2} />
            </span>
            <span style={{ fontSize: 'var(--fs-md)', fontWeight: 600 }}>Key created — copy it now</span>
            <Badge tone="warn">shown only once</Badge>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <code
              style={{
                flex: 1,
                minWidth: 0,
                padding: '9px 12px',
                background: 'var(--bg-base)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--r-md)',
                fontFamily: 'var(--font-mono)',
                fontSize: 'var(--fs-sm)',
                color: 'var(--accent)',
                overflowX: 'auto',
                whiteSpace: 'nowrap',
              }}
            >
              {newSecret.key}
            </code>
            <Button variant="secondary" size="md" icon={copied ? 'check' : 'copy'} onClick={copySecret}>
              {copied ? 'Copied' : 'Copy'}
            </Button>
            <Button variant="ghost" size="md" icon="x" onClick={() => setNewSecret(null)}>
              Dismiss
            </Button>
          </div>
        </Panel>
      )}

      {/* Create form */}
      <Panel style={{ marginBottom: 14 }}>
        <PanelHeader title="Create key" icon="plus" />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 14 }}>
          <div>
            <SectionLabel>Name</SectionLabel>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="ci-pipeline, analytics-reader…"
              style={{ width: '100%', padding: '7px 11px', background: 'var(--bg-surface-3)', border: '1px solid var(--border-strong)', borderRadius: 'var(--r-md)', color: 'var(--text-primary)', fontSize: 'var(--fs-sm)', outline: 'none' }}
            />
          </div>

          <div>
            <SectionLabel>Scopes</SectionLabel>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {SCOPES.map((s) => {
                const on = scopes.includes(s);
                const isAdmin = s === 'admin';
                return (
                  <button
                    key={s}
                    type="button"
                    onClick={() => toggleScope(s)}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 7,
                      padding: '6px 11px',
                      fontSize: 'var(--fs-sm)',
                      fontFamily: 'var(--font-mono)',
                      borderRadius: 'var(--r-md)',
                      border: '1px solid ' + (on ? (isAdmin ? 'var(--block-border)' : 'var(--accent-border)') : 'var(--border-strong)'),
                      background: on ? (isAdmin ? 'var(--block-bg)' : 'var(--accent-surface)') : 'var(--bg-surface-3)',
                      color: on ? (isAdmin ? 'var(--block-bright)' : 'var(--accent)') : 'var(--text-secondary)',
                    }}
                  >
                    <Icon name={on ? 'check' : 'plus'} size={13} />
                    {s}
                  </button>
                );
              })}
            </div>
            {scopes.includes('admin') && (
              <div style={{ marginTop: 8, fontSize: 'var(--fs-xs)', color: 'var(--block-bright)', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <Icon name="warn" size={13} /> The admin scope grants full control over keys and policies.
              </div>
            )}
          </div>

          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 14, flexWrap: 'wrap' }}>
            <div>
              <SectionLabel>Expiry</SectionLabel>
              <Select value={expiryIdx} onChange={setExpiryIdx} minWidth={140} options={EXPIRY_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
            </div>
            <span style={{ flex: 1 }} />
            <Button variant="primary" size="md" icon="plus" onClick={create} disabled={!hasAdmin || creating}>
              Create key
            </Button>
          </div>
          {!hasAdmin && <div style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-muted)' }}>Save an admin credential above to create keys.</div>}
          {createError && <div style={{ fontSize: 'var(--fs-xs)', color: 'var(--block-bright)', fontFamily: 'var(--font-mono)' }}>{createError}</div>}
        </div>
      </Panel>

      {/* Keys table */}
      <Panel pad={false}>
        <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--border)' }}>
          <PanelHeader title="Existing keys" icon="keys" right={<Button variant="ghost" size="sm" icon="refresh" onClick={loadKeys}>Refresh</Button>} />
        </div>
        {!hasAdmin ? (
          <EmptyState icon="keys" title="Enter an admin credential" body="Save an admin-scoped key above to list and manage Collector keys." />
        ) : loading ? (
          <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
            {[0, 1, 2].map((i) => <Skeleton key={i} h={36} r={8} />)}
          </div>
        ) : listError ? (
          <ErrorState title="Failed to load keys" body={listError} onRetry={loadKeys} />
        ) : keys.length === 0 ? (
          <EmptyState icon="keys" title="No keys yet" body="Create your first API key above." />
        ) : (
          <div>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '1.2fr 0.9fr 1.6fr 1fr 1fr 0.7fr 0.5fr',
                padding: '8px 16px',
                background: 'var(--bg-surface-2)',
                borderBottom: '1px solid var(--border)',
                fontSize: 'var(--fs-2xs)',
                fontWeight: 600,
                letterSpacing: '0.05em',
                textTransform: 'uppercase',
                color: 'var(--text-faint)',
              }}
            >
              <span>Name</span>
              <span>Prefix</span>
              <span>Scopes</span>
              <span>Created</span>
              <span>Expires</span>
              <span>Status</span>
              <span style={{ textAlign: 'right' }}>Revoke</span>
            </div>
            {keys.map((k) => {
              const st = keyStatus(k);
              return (
                <div
                  key={k.id}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '1.2fr 0.9fr 1.6fr 1fr 1fr 0.7fr 0.5fr',
                    padding: '11px 16px',
                    borderBottom: '1px solid var(--border-faint)',
                    alignItems: 'center',
                    fontSize: 'var(--fs-sm)',
                  }}
                >
                  <span style={{ color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{k.name}</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-xs)', color: 'var(--text-muted)' }}>{k.key_prefix}</span>
                  <span style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {k.scopes.map((s) => (
                      <Badge key={s} tone={s === 'admin' ? 'block' : 'neutral'} mono style={{ fontSize: 'var(--fs-2xs)', padding: '1px 5px' }}>
                        {s}
                      </Badge>
                    ))}
                  </span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-xs)', color: 'var(--text-muted)' }}>
                    {new Date(k.created_at).toLocaleDateString('en-US')}
                  </span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--fs-xs)', color: 'var(--text-muted)' }}>
                    {k.expires_at ? new Date(k.expires_at).toLocaleDateString('en-US') : 'never'}
                  </span>
                  <span>
                    <Badge tone={st.tone}>{st.label}</Badge>
                  </span>
                  <span style={{ textAlign: 'right' }}>
                    {st.label !== 'revoked' && (
                      <Button variant="ghost" size="sm" icon="trash" onClick={() => revoke(k.id)} />
                    )}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </Panel>
    </div>
  );
}
