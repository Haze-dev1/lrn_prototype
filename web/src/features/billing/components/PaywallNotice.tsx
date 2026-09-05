import Link from 'next/link';

import type { PaywallDetail } from '@/lib/api/billing';

export interface PaywallNoticeProps {
  detail: PaywallDetail;
  /** Overrides the headline for a surface that has already made the argument. */
  heading?: string;
}

/**
 * The message shown when a free-tier limit is reached.
 *
 * It states the limit and what has been used before it offers anything, because a student who has
 * just been stopped mid-task is owed the reason first. A prompt that only sells reads as a trap;
 * one that explains reads as a boundary, and the second is the one people upgrade from.
 *
 * The numbers come from the API's own refusal, never from a client-side count — the server
 * decided, and this renders that decision rather than a second opinion about it.
 */
export function PaywallNotice({ detail, heading }: PaywallNoticeProps) {
  const showMeter = detail.used !== null && detail.limit !== null;
  // Usage can legitimately exceed the allowance — a limit lowered by configuration, or an
  // account whose earlier answers were graded under a larger one. Reporting "53 of 15 used"
  // reads as broken arithmetic and undermines the number next to it, so the meter reports the
  // allowance as spent rather than the raw count.
  const used = showMeter ? Math.min(detail.used as number, detail.limit as number) : 0;

  return (
    <div className="rounded-[--radius-card] border border-accent-muted bg-surface-2 p-5">
      <p className="label-micro text-accent">{heading ?? 'Free tier limit'}</p>
      <p className="mt-2.5 text-sm leading-relaxed text-text-primary">{detail.message}</p>

      {showMeter ? (
        <p className="tabular mt-3 text-xs text-text-muted">
          {used} of {detail.limit} used
        </p>
      ) : null}

      <Link
        href="/pricing"
        className="mt-4 inline-flex h-10 items-center justify-center rounded-md bg-text-primary px-4 text-sm font-medium text-text-inverse transition-colors hover:bg-white"
      >
        See plans
      </Link>
    </div>
  );
}
