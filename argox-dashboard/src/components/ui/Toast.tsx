// Global toast feedback. Mount <ToastProvider> once near the app root, then
// call useToast() anywhere to push success / error / info messages. Toasts
// stack bottom-right, slide in/out, auto-dismiss, can be closed by hand, and
// render through a portal so they are never clipped by an ancestor's overflow.
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Icon, type IconName } from '../shared/Icon';

type Tone = 'success' | 'error' | 'info';

interface ToastItem {
  id: number;
  message: string;
  tone: Tone;
  exiting: boolean;
}

interface ToastApi {
  push: (message: string, tone?: Tone) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const TONE: Record<Tone, { icon: IconName; color: string; border: string }> = {
  success: { icon: 'check', color: 'var(--allow)', border: 'var(--allow-border)' },
  error: { icon: 'warn', color: 'var(--block-bright)', border: 'var(--block-border)' },
  info: { icon: 'spark', color: 'var(--accent)', border: 'var(--accent-border)' },
};

const DURATION = 2800;
const EXIT_MS = 200;
let seq = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const remove = useCallback((id: number) => {
    setItems((list) => list.filter((i) => i.id !== id));
  }, []);

  // Flag the toast as exiting so its slide-out animation plays, then drop it.
  const dismiss = useCallback(
    (id: number) => {
      setItems((list) => list.map((i) => (i.id === id ? { ...i, exiting: true } : i)));
      setTimeout(() => remove(id), EXIT_MS);
    },
    [remove],
  );

  const push = useCallback(
    (message: string, tone: Tone = 'info') => {
      const id = ++seq;
      setItems((list) => [...list, { id, message, tone, exiting: false }]);
      setTimeout(() => dismiss(id), DURATION);
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      push,
      success: (m) => push(m, 'success'),
      error: (m) => push(m, 'error'),
      info: (m) => push(m, 'info'),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      {createPortal(
        <div
          style={{
            position: 'fixed',
            bottom: 24,
            right: 24,
            zIndex: 3000,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'flex-end',
            gap: 8,
            pointerEvents: 'none',
          }}
        >
          {items.map((t) => {
            const tone = TONE[t.tone];
            return (
              <div
                key={t.id}
                className={t.exiting ? 'ax-toast-out' : 'ax-toast-in'}
                role="status"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 9,
                  padding: '10px 12px 10px 16px',
                  maxWidth: 420,
                  background: 'var(--bg-overlay)',
                  border: '1px solid ' + tone.border,
                  borderRadius: 'var(--r-md)',
                  boxShadow: 'var(--shadow-pop)',
                  pointerEvents: 'auto',
                }}
              >
                <span style={{ color: tone.color, display: 'flex', flex: '0 0 auto' }}>
                  <Icon name={tone.icon} size={16} strokeWidth={2} />
                </span>
                <span style={{ fontSize: 'var(--fs-sm)', color: 'var(--text-primary)', fontWeight: 550 }}>{t.message}</span>
                <button
                  type="button"
                  aria-label="Dismiss"
                  onClick={() => dismiss(t.id)}
                  style={{
                    display: 'flex',
                    flex: '0 0 auto',
                    marginLeft: 4,
                    padding: 3,
                    borderRadius: 'var(--r-sm)',
                    border: 'none',
                    background: 'transparent',
                    color: 'var(--text-faint)',
                    transition: 'color var(--transition), background var(--transition)',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.color = 'var(--text-primary)';
                    e.currentTarget.style.background = 'var(--bg-surface-3)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.color = 'var(--text-faint)';
                    e.currentTarget.style.background = 'transparent';
                  }}
                >
                  <Icon name="x" size={13} strokeWidth={2} />
                </button>
              </div>
            );
          })}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within <ToastProvider>');
  return ctx;
}
