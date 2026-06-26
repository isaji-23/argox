// Read-key entry modal.
//
// Opened by the header key button or automatically on the `auth-required`
// event. On save it validates (rejecting control chars) and persists the read
// key via `setToken`; the shell reacts to `token-changed` to refetch.
import { useEffect, useRef, useState } from 'react';
import { getToken, setToken, clearToken } from '../../lib/auth';
import { Icon } from '../shared/Icon';
import { Button } from './Button';
import { useToast } from './Toast';

interface AuthDialogProps {
  open: boolean;
  onClose: () => void;
  /** True when the dialog was opened by a 401/403 (shows the prompt hint). */
  prompted?: boolean;
}

export function AuthDialog({ open, onClose, prompted }: AuthDialogProps) {
  const [value, setValue] = useState('');
  const [reveal, setReveal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hasStored = !!getToken();
  const inputRef = useRef<HTMLInputElement>(null);
  const toast = useToast();

  useEffect(() => {
    if (open) {
      setValue('');
      setError(null);
      setReveal(false);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  if (!open) return null;

  const save = () => {
    if (!value.trim()) {
      setError('Enter a Collector API key with the read scope.');
      return;
    }
    if (!setToken(value)) {
      setError('Invalid key: it contains control characters. Re-copy and try again.');
      return;
    }
    toast.success('API key saved');
    onClose();
  };

  const remove = () => {
    clearToken();
    toast.info('API key removed');
    onClose();
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 2000,
        background: 'rgba(4, 8, 16, 0.55)',
        backdropFilter: 'blur(3px)',
        display: 'grid',
        placeItems: 'center',
        padding: 20,
      }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="ax-fade-in"
        style={{
          width: 440,
          maxWidth: '100%',
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-strong)',
          borderRadius: 'var(--r-lg)',
          boxShadow: 'var(--shadow-lg)',
          padding: 'var(--sp-5)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
          <span style={{ color: 'var(--accent)', display: 'flex' }}>
            <Icon name="eye" size={18} />
          </span>
          <h2 style={{ margin: 0, fontSize: 'var(--fs-lg)', fontWeight: 600 }}>Collector API key</h2>
        </div>
        <p style={{ margin: '0 0 14px', fontSize: 'var(--fs-sm)', color: 'var(--text-muted)', lineHeight: 1.5 }}>
          {prompted
            ? 'The Collector rejected the request. Paste an API key with the read scope to continue.'
            : 'Paste an API key with the read scope. Stored locally in this browser only.'}
        </p>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '7px 11px',
            background: 'var(--bg-surface-3)',
            border: '1px solid ' + (error ? 'var(--block-border)' : 'var(--border-strong)'),
            borderRadius: 'var(--r-md)',
          }}
        >
          <input
            ref={inputRef}
            type={reveal ? 'text' : 'password'}
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              setError(null);
            }}
            onKeyDown={(e) => e.key === 'Enter' && save()}
            placeholder="argox_sk_…"
            style={{
              flex: 1,
              minWidth: 0,
              background: 'transparent',
              border: 'none',
              outline: 'none',
              color: 'var(--text-primary)',
              fontSize: 'var(--fs-sm)',
              fontFamily: 'var(--font-mono)',
            }}
          />
          <button
            type="button"
            onClick={() => setReveal((r) => !r)}
            style={{ background: 'none', border: 'none', color: 'var(--text-muted)', display: 'flex', padding: 0 }}
          >
            <Icon name={reveal ? 'eyeOff' : 'eye'} size={15} />
          </button>
        </div>
        {error && (
          <div style={{ marginTop: 8, fontSize: 'var(--fs-xs)', color: 'var(--block-bright)', fontFamily: 'var(--font-mono)' }}>
            {error}
          </div>
        )}

        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 18 }}>
          <Button variant="primary" size="md" icon="check" onClick={save}>
            Save key
          </Button>
          {hasStored && (
            <Button variant="ghost" size="md" icon="trash" onClick={remove}>
              Remove
            </Button>
          )}
          <span style={{ flex: 1 }} />
          <Button variant="ghost" size="md" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </div>
    </div>
  );
}
