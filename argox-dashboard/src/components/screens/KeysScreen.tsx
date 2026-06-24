import { useState, useEffect, useCallback } from 'react';
import { api, APIError } from '../../lib/api';
import type { ApiKeyView, ApiKeyCreateResponse, KeyScope } from '../../lib/api';
import {
  getAdminToken,
  setAdminToken,
  clearAdminToken,
  ADMIN_TOKEN_CHANGED_EVENT,
  authBus,
} from '../../lib/auth';
import { Icon } from '../shared/Icon';
import { Button, IconButton } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { Skeleton, ErrorState, EmptyState } from '../ui/States';

// Scopes the operator can grant from the UI, in display order. `admin` implies
// every other scope (see Collector principal.py), so it is offered last with a
// warning tone.
const SCOPE_OPTIONS: { value: KeyScope; label: string }[] = [
  { value: 'read', label: 'read' },
  { value: 'ingest', label: 'ingest' },
  { value: 'policy-read', label: 'policy-read' },
  { value: 'policy-write', label: 'policy-write' },
  { value: 'admin', label: 'admin' },
];

// Optional key lifetimes, mapped to seconds for the `expires_in` field.
const EXPIRY_OPTIONS: { label: string; seconds: number | null }[] = [
  { label: 'Never', seconds: null },
  { label: '30 days', seconds: 30 * 86400 },
  { label: '90 days', seconds: 90 * 86400 },
  { label: '1 year', seconds: 365 * 86400 },
];

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function keyStatus(key: ApiKeyView): { label: string; tone: 'allow' | 'block' | 'warn' } {
  if (key.revoked) return { label: 'revoked', tone: 'block' };
  if (key.expires_at && new Date(key.expires_at).getTime() < Date.now()) {
    return { label: 'expired', tone: 'warn' };
  }
  return { label: 'active', tone: 'allow' };
}

export function KeysScreen() {
  // Admin credential, persisted in its own localStorage slot.
  const [adminKey, setAdminKey] = useState(() => getAdminToken() ?? '');
  const [reveal, setReveal] = useState(false);
  const [credInvalid, setCredInvalid] = useState(false);

  // Key list.
  const [keys, setKeys] = useState<ApiKeyView[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Create form.
  const [name, setName] = useState('');
  const [scopes, setScopes] = useState<KeyScope[]>(['read']);
  const [expiryIdx, setExpiryIdx] = useState(0);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // One-time raw secret shown after a successful create.
  const [newSecret, setNewSecret] = useState<ApiKeyCreateResponse | null>(null);
  const [copied, setCopied] = useState(false);

  const hasAdminKey = Boolean(getAdminToken());

  const fetchKeys = useCallback(async () => {
    if (!getAdminToken()) {
      setKeys([]);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await api.listKeys();
      // Newest first; the backend already orders this way, but be defensive.
      setKeys(res.keys);
    } catch (err) {
      setError(err instanceof APIError ? err.message : 'Failed to list API keys');
    } finally {
      setLoading(false);
    }
  }, []);

  // Refetch whenever the admin credential changes (including from another tab).
  useEffect(() => {
    fetchKeys();
    const onChange = () => {
      setAdminKey(getAdminToken() ?? '');
      fetchKeys();
    };
    authBus.addEventListener(ADMIN_TOKEN_CHANGED_EVENT, onChange);
    window.addEventListener('storage', onChange);
    return () => {
      authBus.removeEventListener(ADMIN_TOKEN_CHANGED_EVENT, onChange);
      window.removeEventListener('storage', onChange);
    };
  }, [fetchKeys]);

  const handleSaveCred = () => {
    if (!setAdminToken(adminKey)) {
      setCredInvalid(true);
      return;
    }
    setCredInvalid(false);
  };

  const handleClearCred = () => {
    clearAdminToken();
    setAdminKey('');
    setCredInvalid(false);
  };

  const toggleScope = (scope: KeyScope) => {
    setScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope],
    );
  };

  const handleCreate = async () => {
    setCreateError(null);
    if (!name.trim()) {
      setCreateError('Name is required.');
      return;
    }
    if (scopes.length === 0) {
      setCreateError('Select at least one scope.');
      return;
    }
    setCreating(true);
    try {
      const seconds = EXPIRY_OPTIONS[expiryIdx].seconds;
      const res = await api.createKey({
        name: name.trim(),
        scopes,
        ...(seconds !== null ? { expires_in: seconds } : {}),
      });
      setNewSecret(res);
      setCopied(false);
      setName('');
      setScopes(['read']);
      setExpiryIdx(0);
      fetchKeys();
    } catch (err) {
      setCreateError(err instanceof APIError ? err.message : 'Failed to create API key');
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (key: ApiKeyView) => {
    if (!window.confirm(`Revoke key "${key.name}" (${key.key_prefix}…)? This cannot be undone.`)) {
      return;
    }
    try {
      await api.revokeKey(key.id);
      fetchKeys();
    } catch (err) {
      setError(err instanceof APIError ? err.message : 'Failed to revoke key');
    }
  };

  const copySecret = async () => {
    if (!newSecret) return;
    try {
      await navigator.clipboard.writeText(newSecret.key);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="p-6 flex flex-col gap-5 max-w-[920px]">
      {/* Admin credential */}
      <section className="bg-surface border border-border rounded-xl overflow-hidden">
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-border">
          <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-surface-3 border border-border text-text-secondary">
            <Icon name="key" size={16} />
          </span>
          <div className="flex-1 min-w-0">
            <div className="text-md font-semibold text-text-primary">Admin credential</div>
            <div className="text-sm text-text-muted">
              An <span className="font-mono">admin</span>-scoped key is required to manage keys. Stored only in this browser.
            </div>
          </div>
          {hasAdminKey && <Badge tone="allow">connected</Badge>}
        </div>
        <div className="px-5 py-4 flex flex-col gap-3">
          {credInvalid && (
            <div className="flex items-start gap-2 text-sm text-block-bright bg-block-bg border border-block-border rounded-md px-3 py-2 leading-normal">
              <Icon name="warn" size={15} className="mt-0.5 flex-shrink-0" />
              <span>Invalid key: remove line breaks or control characters and try again.</span>
            </div>
          )}
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-2 flex-1 bg-surface-3 border border-border-strong rounded-md px-2.5 focus-within:border-accent transition-colors">
              <input
                type={reveal ? 'text' : 'password'}
                value={adminKey}
                onChange={(e) => { setAdminKey(e.target.value); setCredInvalid(false); }}
                onKeyDown={(e) => { if (e.key === 'Enter') handleSaveCred(); }}
                placeholder="argox_… (admin scope)"
                autoComplete="off"
                spellCheck={false}
                className="flex-1 bg-transparent py-2 text-base text-text-primary font-mono outline-none placeholder:text-text-faint"
              />
              <IconButton
                name={reveal ? 'eyeOff' : 'eye'}
                label={reveal ? 'Hide key' : 'Show key'}
                onClick={() => setReveal((r) => !r)}
              />
            </div>
            <Button variant="primary" size="sm" icon="check" onClick={handleSaveCred}>
              Save
            </Button>
            {hasAdminKey && (
              <Button variant="ghost" size="sm" icon="x" onClick={handleClearCred}>
                Remove
              </Button>
            )}
          </div>
          <div className="text-sm text-text-muted leading-normal">
            The break-glass <span className="font-mono">ARGOX_BOOTSTRAP_ADMIN_KEY</span> works, but prefer
            minting a dedicated <span className="font-mono">admin</span> key for day-to-day use.
          </div>
        </div>
      </section>

      {/* One-time secret */}
      {newSecret && (
        <section className="bg-gold-surface border border-gold-border rounded-xl overflow-hidden">
          <div className="flex items-center gap-2.5 px-5 py-3 border-b border-gold-border">
            <Icon name="warn" size={16} className="text-gold-bright" />
            <div className="flex-1 text-md font-semibold text-text-primary">
              Copy this key now — it is shown only once
            </div>
            <IconButton name="x" label="Dismiss" onClick={() => setNewSecret(null)} />
          </div>
          <div className="px-5 py-4 flex flex-col gap-2">
            <div className="text-sm text-text-muted">
              Key <span className="font-semibold text-text-primary">{newSecret.name}</span> ·
              scopes <span className="font-mono">{newSecret.scopes.join(', ')}</span>
            </div>
            <div className="flex items-center gap-2 bg-surface-3 border border-border-strong rounded-md px-3 py-2">
              <code className="flex-1 text-base text-text-primary font-mono break-all">{newSecret.key}</code>
              <Button
                variant={copied ? 'primary' : 'secondary'}
                size="sm"
                icon={copied ? 'check' : 'copy'}
                onClick={copySecret}
              >
                {copied ? 'Copied' : 'Copy'}
              </Button>
            </div>
            <div className="text-sm text-text-muted leading-normal">
              The Collector stores only a hash — it cannot be retrieved later. If you lose it, revoke and mint a new one.
            </div>
          </div>
        </section>
      )}

      {/* Create form */}
      <section className="bg-surface border border-border rounded-xl overflow-hidden">
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-border">
          <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-surface-3 border border-border text-text-secondary">
            <Icon name="plus" size={16} />
          </span>
          <div className="flex-1 min-w-0">
            <div className="text-md font-semibold text-text-primary">Create a key</div>
            <div className="text-sm text-text-muted">Mint a new API key with the selected scopes.</div>
          </div>
        </div>
        <div className="px-5 py-4 flex flex-col gap-4">
          {createError && (
            <div className="flex items-start gap-2 text-sm text-block-bright bg-block-bg border border-block-border rounded-md px-3 py-2 leading-normal">
              <Icon name="warn" size={15} className="mt-0.5 flex-shrink-0" />
              <span>{createError}</span>
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-text-secondary">Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. dashboard-read, ci-ingest"
              maxLength={200}
              spellCheck={false}
              className="bg-surface-3 border border-border-strong rounded-md px-2.5 py-2 text-base text-text-primary outline-none focus:border-accent transition-colors placeholder:text-text-faint"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-text-secondary">Scopes</label>
            <div className="flex flex-wrap gap-2">
              {SCOPE_OPTIONS.map((opt) => {
                const checked = scopes.includes(opt.value);
                const isAdmin = opt.value === 'admin';
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => toggleScope(opt.value)}
                    className={
                      'inline-flex items-center gap-1.5 px-2.5 py-1.5 text-sm font-mono font-semibold border rounded-md transition-all ' +
                      (checked
                        ? (isAdmin
                          ? 'text-block-bright bg-block-bg border-block-border'
                          : 'text-accent bg-accent-surface border-accent-border')
                        : 'text-text-secondary bg-surface-3 border-border hover:border-border-strong')
                    }
                  >
                    {checked && <Icon name="check" size={13} />}
                    {opt.label}
                  </button>
                );
              })}
            </div>
            {scopes.includes('admin') && (
              <div className="text-sm text-block-bright leading-normal mt-0.5">
                The <span className="font-mono">admin</span> scope grants full control, including key management.
              </div>
            )}
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-text-secondary">Expires</label>
            <div className="flex flex-wrap gap-2">
              {EXPIRY_OPTIONS.map((opt, idx) => (
                <button
                  key={opt.label}
                  type="button"
                  onClick={() => setExpiryIdx(idx)}
                  className={
                    'px-2.5 py-1.5 text-sm font-semibold border rounded-md transition-all ' +
                    (expiryIdx === idx
                      ? 'text-accent bg-accent-surface border-accent-border'
                      : 'text-text-secondary bg-surface-3 border-border hover:border-border-strong')
                  }
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <Button
              variant="primary"
              size="md"
              icon="plus"
              onClick={handleCreate}
              disabled={creating || !hasAdminKey}
            >
              {creating ? 'Creating…' : 'Create key'}
            </Button>
            {!hasAdminKey && (
              <span className="ml-3 text-sm text-text-muted">Save an admin credential first.</span>
            )}
          </div>
        </div>
      </section>

      {/* Existing keys */}
      <section className="bg-surface border border-border rounded-xl overflow-hidden">
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-border">
          <div className="flex-1 min-w-0">
            <div className="text-md font-semibold text-text-primary">Existing keys</div>
            <div className="text-sm text-text-muted">Metadata only — secrets are never stored or shown again.</div>
          </div>
          <IconButton name="refresh" label="Refresh" onClick={fetchKeys} />
        </div>
        <div className="px-5 py-4">
          {!hasAdminKey ? (
            <EmptyState
              icon="key"
              title="No admin credential"
              body="Save an admin-scoped key above to list and manage Collector API keys."
            />
          ) : loading ? (
            <div className="flex flex-col gap-2">
              {[0, 1, 2].map((i) => <Skeleton key={i} h={40} />)}
            </div>
          ) : error ? (
            <ErrorState title="Failed to load keys" body={error} onRetry={fetchKeys} />
          ) : keys.length === 0 ? (
            <EmptyState icon="key" title="No keys yet" body="Create your first API key with the form above." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-base border-collapse">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-text-faint">
                    <th className="font-semibold px-2 py-2">Name</th>
                    <th className="font-semibold px-2 py-2">Prefix</th>
                    <th className="font-semibold px-2 py-2">Scopes</th>
                    <th className="font-semibold px-2 py-2">Created</th>
                    <th className="font-semibold px-2 py-2">Expires</th>
                    <th className="font-semibold px-2 py-2">Status</th>
                    <th className="font-semibold px-2 py-2 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {keys.map((key) => {
                    const status = keyStatus(key);
                    return (
                      <tr key={key.id} className="border-t border-border">
                        <td className="px-2 py-2.5 text-text-primary">{key.name}</td>
                        <td className="px-2 py-2.5 font-mono text-text-secondary">{key.key_prefix}…</td>
                        <td className="px-2 py-2.5">
                          <div className="flex flex-wrap gap-1">
                            {key.scopes.map((s) => (
                              <Badge key={s} tone={s === 'admin' ? 'block' : 'neutral'} mono>{s}</Badge>
                            ))}
                          </div>
                        </td>
                        <td className="px-2 py-2.5 text-text-muted whitespace-nowrap">{formatDate(key.created_at)}</td>
                        <td className="px-2 py-2.5 text-text-muted whitespace-nowrap">{formatDate(key.expires_at)}</td>
                        <td className="px-2 py-2.5"><Badge tone={status.tone}>{status.label}</Badge></td>
                        <td className="px-2 py-2.5 text-right">
                          {!key.revoked && (
                            <Button variant="danger" size="sm" icon="ban" onClick={() => handleRevoke(key)}>
                              Revoke
                            </Button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
