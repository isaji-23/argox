import React from 'react';
import { cn } from '../../lib/utils';
import { Icon } from '../shared/Icon';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'outline' | 'danger' | 'accentSoft';
  size?: 'sm' | 'md' | 'lg';
  icon?: string;
  iconRight?: string;
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
  className,
  ...props
}: ButtonProps) {
  const variants = {
    primary: "bg-accent text-accent-fg border-accent shadow-[0_1px_0_rgba(255,255,255,0.12)_inset]",
    secondary: "bg-surface-3 text-text-primary border-border-strong",
    ghost: cn(
      "border-transparent",
      active ? "bg-surface-3 text-text-primary border-border" : "bg-transparent text-text-secondary"
    ),
    outline: "bg-transparent text-text-primary border-border-strong",
    danger: "bg-block-bg text-block-bright border-block-border",
    accentSoft: "bg-accent-surface text-accent border-accent-border",
  };

  const sizes = {
    sm: "px-2.5 py-1.5 text-sm gap-1.5",
    md: "px-3 py-2 text-base gap-2",
    lg: "px-4.5 py-2.5 text-md gap-2",
  };

  return (
    <button
      className={cn(
        "inline-flex items-center justify-center font-semibold font-ui rounded-md border transition-all select-none whitespace-nowrap leading-none",
        variants[variant],
        sizes[size],
        full && "w-full",
        className
      )}
      {...props}
    >
      {icon && <Icon name={icon} size={size === 'sm' ? 14 : 15} />}
      {children}
      {iconRight && <Icon name={iconRight} size={size === 'sm' ? 14 : 15} />}
    </button>
  );
}

interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  name: string;
  size?: number;
  label: string;
  active?: boolean;
}

export function IconButton({ name, size = 16, label, active, className, ...props }: IconButtonProps) {
  return (
    <button
      title={label}
      aria-label={label}
      className={cn(
        "inline-flex items-center justify-center w-8 h-8 rounded-md transition-all border",
        active ? "bg-surface-3 text-text-primary border-border" : "bg-transparent text-text-secondary border-transparent",
        className
      )}
      {...props}
    >
      <Icon name={name} size={size} />
    </button>
  );
}
