/** Native select styled to the design tokens. Native, so mobile gets the platform picker. */

import type { SelectHTMLAttributes } from 'react';

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'className'> {
  invalid?: boolean;
}

export function Select({ invalid = false, children, ...props }: SelectProps) {
  return (
    <select
      {...props}
      aria-invalid={invalid || undefined}
      className={[
        'w-full appearance-none rounded-md bg-surface-2 px-3 py-2.5 text-sm text-text-primary',
        'border transition-colors disabled:cursor-not-allowed disabled:opacity-60',
        invalid ? 'border-band-needs-work' : 'border-border-subtle hover:border-border-strong',
      ].join(' ')}
    >
      {children}
    </select>
  );
}
