/** Text input styled to the design tokens, with a visible invalid state. */

import type { InputHTMLAttributes } from 'react';

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'className'> {
  invalid?: boolean;
}

export function Input({ invalid = false, ...props }: InputProps) {
  return (
    <input
      {...props}
      aria-invalid={invalid || undefined}
      className={[
        'w-full rounded-md bg-surface-2 px-3 py-2.5 text-sm text-text-primary',
        'border transition-colors placeholder:text-text-muted',
        'disabled:cursor-not-allowed disabled:opacity-60',
        invalid ? 'border-band-needs-work' : 'border-border-subtle hover:border-border-strong',
      ].join(' ')}
    />
  );
}
