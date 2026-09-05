/**
 * Primary action control.
 *
 * Domain-neutral by design: it renders an action and reports a click. Business rules for whether
 * an action is permitted belong to the feature module that owns the workflow.
 */

import type { ButtonHTMLAttributes, ReactNode } from 'react';

type ButtonVariant = 'primary' | 'secondary' | 'ghost';
type ButtonSize = 'sm' | 'md' | 'lg';

export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'className'> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Renders a busy state and blocks interaction while an action is in flight. */
  loading?: boolean;
  /** Stretch to the container width, for the primary action in a form or card. */
  fullWidth?: boolean;
  children: ReactNode;
}

const VARIANT_STYLES: Record<ButtonVariant, string> = {
  // Bone-white rather than a saturated brand colour: maximum contrast for the single most
  // important action on a page, without adding another competing hue.
  primary:
    'bg-text-primary text-text-inverse hover:bg-white disabled:bg-surface-3 disabled:text-text-muted',
  secondary:
    'bg-surface-2 text-text-primary border border-border-subtle hover:border-border-strong hover:bg-surface-3 disabled:text-text-muted',
  ghost: 'text-text-secondary hover:text-text-primary hover:bg-surface-2 disabled:text-text-muted',
};

const SIZE_STYLES: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-sm',
  md: 'h-10 px-4 text-sm',
  lg: 'h-12 px-6 text-base',
};

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  fullWidth = false,
  disabled,
  children,
  ...props
}: ButtonProps) {
  const isDisabled = disabled === true || loading;

  return (
    <button
      {...props}
      disabled={isDisabled}
      aria-busy={loading}
      className={[
        'inline-flex items-center justify-center gap-2 rounded-md font-medium',
        'transition-colors duration-150 disabled:cursor-not-allowed',
        VARIANT_STYLES[variant],
        SIZE_STYLES[size],
        fullWidth ? 'w-full' : '',
      ].join(' ')}
    >
      {loading ? <Spinner /> : null}
      {children}
    </button>
  );
}

/** Minimal busy indicator, hidden from assistive tech since `aria-busy` already conveys state. */
function Spinner() {
  return (
    <span
      aria-hidden="true"
      className="size-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"
    />
  );
}
