import { useEffect, useRef, useState } from 'react';
import { Icon } from '../shared/Icon';
import { Button, IconButton } from './Button';
import { getToken, setToken, clearToken } from '../../lib/auth';

interface AuthDialogProps {
  open: boolean;
  /** Set when the dialog was opened in reaction to a 401/403 response. */
  authError?: boolean;
  onClose: () => void;
  /** Called after a key is saved or cleared, so the caller can refetch. */
  onSaved: () => void;
}

/**
 * Modal for entering the Collector API key used to authenticate dashboard
 * queries. The key is persisted to `localStorage` via the auth store and never
 * embedded in the bundle. Closing without a stored key leaves the dashboard
 * unauthenticated (fine when `ARGOX_AUTH_ENABLED=false`).
 */
export function AuthDialog({ open, authError, onClose, onSaved }: AuthDialogProps) {
  const [value, setValue] = useState('');
  const [reveal, setReveal] = useState(false);
  const [invalid, setInvalid] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Seed the field with the stored key (if any) each time the dialog opens.
  useEffect(() => {
    if (open) {
      setValue(getToken() ?? '');
      setReveal(false);
      setInvalid(false);
      // Focus after the element mounts.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const handleSave = () => {
    if (!setToken(value)) {
      setInvalid(true);
      return;
    }
    onSaved();
    onClose();
  };

  const handleClear = () => {
    clearToken();
    setValue('');
    onSaved();
  };

  const hasStoredKey = Boolean(getToken());

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Collector API key"
        className="w-full max-w-[440px] bg-surface border border-border rounded-xl shadow-lg overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-border">
          <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-surface-3 border border-border text-text-secondary">
            <Icon name="key" size={16} />
          </span>
          <div className="flex-1 min-w-0">
            <div className="text-md font-semibold text-text-primary">Collector API key</div>
            <div className="text-sm text-text-muted">Required to read traces and metrics when auth is enabled.</div>
          </div>
          <IconButton name="x" label="Close" onClick={onClose} />
        </div>

        <div className="px-5 py-4 flex flex-col gap-3">
          {authError && !invalid && (
            <div className="flex items-start gap-2 text-sm text-block-bright bg-block-bg border border-block-border rounded-md px-3 py-2 leading-normal">
              <Icon name="warn" size={15} className="mt-0.5 flex-shrink-0" />
              <span>The Collector rejected the request. Enter a valid key with the <span className="font-mono">read</span> scope.</span>
            </div>
          )}
          {invalid && (
            <div className="flex items-start gap-2 text-sm text-block-bright bg-block-bg border border-block-border rounded-md px-3 py-2 leading-normal">
              <Icon name="warn" size={15} className="mt-0.5 flex-shrink-0" />
              <span>Invalid key: remove line breaks or control characters and try again.</span>
            </div>
          )}

          <label className="text-sm font-medium text-text-secondary">API key</label>
          <div className="flex items-center gap-2 bg-surface-3 border border-border-strong rounded-md px-2.5 focus-within:border-accent transition-colors">
            <input
              ref={inputRef}
              type={reveal ? 'text' : 'password'}
              value={value}
              onChange={(e) => { setValue(e.target.value); setInvalid(false); }}
              onKeyDown={(e) => { if (e.key === 'Enter') handleSave(); }}
              placeholder="argox_…"
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
          <div className="text-sm text-text-muted leading-normal">
            Stored only in this browser (<span className="font-mono">localStorage</span>) and sent as a
            <span className="font-mono"> Bearer</span> token. Leave empty if the Collector runs with auth disabled.
          </div>
        </div>

        <div className="flex items-center justify-between gap-2 px-5 py-4 border-t border-border bg-surface-2">
          <div>
            {hasStoredKey && (
              <Button variant="ghost" size="sm" icon="x" onClick={handleClear}>
                Remove key
              </Button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" icon="check" onClick={handleSave}>
              Save
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
