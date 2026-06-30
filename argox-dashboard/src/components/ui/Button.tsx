// Button + IconButton primitives (peacock design system).
import type { ButtonHTMLAttributes, CSSProperties, ReactNode } from 'react';
import { Icon, type IconName } from '../shared/Icon';

type Variant = 'primary' | 'secondary' | 'ghost' | 'outline' | 'danger' | 'accentSoft';
type Size = 'sm' | 'md' | 'lg';

interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'type'> {
  children?: ReactNode;
  variant?: Variant;
  size?: Size;
  icon?: IconName;
  iconRight?: IconName;
  full?: boolean;
  active?: boolean;
}

export function Button({
  children,
  variant = 'secondary',
  size = 'md',
  icon,
  iconRight,
  full,
  active,
  style,
  className,
  ...rest
}: ButtonProps) {
  const pad = size === 'sm' ? '5px 10px' : size === 'lg' ? '10px 18px' : '7px 13px';
  const fs = size === 'sm' ? 'var(--fs-sm)' : size === 'lg' ? 'var(--fs-md)' : 'var(--fs-base)';
  const base: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 7,
    padding: pad,
    fontSize: fs,
    fontWeight: 550,
    fontFamily: 'var(--font-ui)',
    borderRadius: 'var(--r-md)',
    border: '1px solid transparent',
    lineHeight: 1,
    transition:
      'background var(--transition), border-color var(--transition), color var(--transition), box-shadow var(--transition), transform var(--transition)',
    width: full ? '100%' : undefined,
    whiteSpace: 'nowrap',
    userSelect: 'none',
  };
  const variants: Record<Variant, CSSProperties> = {
    primary: {
      background: 'var(--accent)',
      color: 'var(--accent-fg)',
      borderColor: 'var(--accent)',
      boxShadow: '0 1px 0 rgba(255,255,255,0.12) inset',
    },
    secondary: {
      background: 'var(--bg-surface-3)',
      color: 'var(--text-primary)',
      borderColor: 'var(--border-strong)',
    },
    ghost: {
      background: active ? 'var(--bg-surface-3)' : 'transparent',
      color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
      borderColor: active ? 'var(--border)' : 'transparent',
    },
    outline: { background: 'transparent', color: 'var(--text-primary)', borderColor: 'var(--border-strong)' },
    danger: { background: 'var(--block-bg)', color: 'var(--block-bright)', borderColor: 'var(--block-border)' },
    accentSoft: { background: 'var(--accent-surface)', color: 'var(--accent)', borderColor: 'var(--accent-border)' },
  };
  return (
    <button
      type="button"
      {...rest}
      className={className}
      style={{ ...base, ...variants[variant], ...style }}
    >
      {icon && <Icon name={icon} size={size === 'sm' ? 14 : 15} />}
      {children}
      {iconRight && <Icon name={iconRight} size={size === 'sm' ? 14 : 15} />}
    </button>
  );
}

interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'type'> {
  name: IconName | string;
  size?: number;
  label?: string;
  active?: boolean;
}

export function IconButton({ name, size = 16, label, active, style, ...rest }: IconButtonProps) {
  return (
    <button
      type="button"
      {...rest}
      title={label}
      aria-label={label}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 32,
        height: 32,
        borderRadius: 'var(--r-md)',
        background: active ? 'var(--bg-surface-3)' : 'transparent',
        color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
        border: '1px solid ' + (active ? 'var(--border)' : 'transparent'),
        transition: 'all var(--transition)',
        ...style,
      }}
    >
      <Icon name={name} size={size} />
    </button>
  );
}
