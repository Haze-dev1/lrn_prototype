/**
 * Labelled form field wrapper.
 *
 * Owns the label association, hint and error wiring so every form in the product reports
 * validation the same way, and so screen readers always announce the error with the input rather
 * than as loose text elsewhere on the page.
 */

import type { ReactNode } from 'react';

export interface FieldProps {
  id: string;
  label: string;
  hint?: string;
  error?: string | null;
  children: ReactNode;
}

export function Field({ id, label, hint, error, children }: FieldProps) {
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;

  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium text-text-primary">
        {label}
      </label>
      {hint ? (
        <p id={hintId} className="text-xs text-text-muted">
          {hint}
        </p>
      ) : null}
      {children}
      {error ? (
        <p id={errorId} role="alert" className="text-xs text-band-needs-work">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** Compose the aria-describedby value for an input inside a Field. */
export function describedBy(id: string, hint?: string, error?: string | null): string | undefined {
  const ids = [hint ? `${id}-hint` : null, error ? `${id}-error` : null].filter(Boolean);
  return ids.length > 0 ? ids.join(' ') : undefined;
}
