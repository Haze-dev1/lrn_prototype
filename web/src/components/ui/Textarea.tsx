/**
 * Multi-line text input styled to the design tokens.
 *
 * Sized generously by default: the fields it serves are interview prompts and reference answers,
 * and a three-row box makes an author scroll while writing the most important content in the
 * product.
 */

import type { ComponentPropsWithRef } from 'react';

// ComponentPropsWithRef rather than TextareaHTMLAttributes: React 19 passes `ref` to function
// components as an ordinary prop, and the assessment composer needs one to take focus when the
// student moves to a new question.
export interface TextareaProps extends ComponentPropsWithRef<'textarea'> {
  invalid?: boolean;
  /** Render in monospace, for structured content where alignment carries meaning. */
  mono?: boolean;
}

export function Textarea({ invalid = false, mono = false, rows = 5, className, ...props }: TextareaProps) {
  return (
    <textarea
      {...props}
      rows={rows}
      aria-invalid={invalid || undefined}
      className={[
        'w-full resize-y rounded-md bg-surface-2 px-3 py-2.5 text-sm text-text-primary',
        'border transition-colors placeholder:text-text-muted',
        'disabled:cursor-not-allowed disabled:opacity-60',
        mono ? 'font-mono text-xs leading-relaxed' : 'leading-relaxed',
        invalid ? 'border-band-needs-work' : 'border-border-subtle hover:border-border-strong',
        className || '',
      ].join(' ')}
    />
  );
}
