/**
 * Compact status label.
 *
 * Tone maps to the product's mastery bands so a "Strong" badge is the same colour wherever it
 * appears — on a graded answer, a category row, or the dashboard.
 */

import type { ReactNode } from 'react';

export type BadgeTone = 'neutral' | 'strong' | 'developing' | 'needs-work';

export interface BadgeProps {
  tone?: BadgeTone;
  children: ReactNode;
}

const TONE_STYLES: Record<BadgeTone, string> = {
  neutral: 'text-text-secondary border-border-subtle',
  strong: 'text-band-strong border-band-strong/35',
  developing: 'text-band-developing border-band-developing/35',
  'needs-work': 'text-band-needs-work border-band-needs-work/35',
};

export function Badge({ tone = 'neutral', children }: BadgeProps) {
  return (
    <span
      className={[
        'inline-flex items-center rounded border px-2 py-0.5',
        'font-mono text-[0.6875rem] tracking-[0.1em] uppercase',
        TONE_STYLES[tone],
      ].join(' ')}
    >
      {children}
    </span>
  );
}
