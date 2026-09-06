/**
 * Inline status message.
 *
 * Errors use role="alert" so assistive technology announces a failed submission immediately;
 * without it a screen-reader user gets no feedback that anything went wrong.
 */

import type { ReactNode } from 'react';

import { cn } from '@/utils/cn';

export type AlertTone = 'error' | 'success' | 'info';

const TONE_STYLES: Record<AlertTone, string> = {
  error: 'border-band-needs-work/40 bg-band-needs-work/10 text-band-needs-work',
  success: 'border-band-strong/40 bg-band-strong/10 text-band-strong',
  info: 'border-border-subtle bg-surface-2 text-text-secondary',
};

export interface AlertProps {
  tone?: AlertTone;
  children: ReactNode;
  className?: string;
}

export function Alert({ tone = 'info', children, className }: AlertProps) {
  return (
    <div
      role={tone === 'error' ? 'alert' : 'status'}
      // `className` was accepted and then dropped, so callers passing spacing got none.
      className={cn('rounded-md border px-3 py-2.5 text-sm', TONE_STYLES[tone], className)}
    >
      {children}
    </div>
  );
}
