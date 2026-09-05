import Link from 'next/link';

import type { Entitlement } from '@/lib/api/billing';

export interface AllowanceMeterProps {
  entitlement: Entitlement;
  /** Which allowance to show. */
  kind: 'practice' | 'grading';
}

/**
 * How much of a free allowance is left, shown before it runs out.
 *
 * Renders nothing for a paid account — there is no allowance to report, and a meter reading
 * "unlimited" is noise on every page it appears.
 *
 * Showing the remainder up front is what makes the limit feel like a boundary rather than an
 * ambush. A student who knows they have one set left can choose how to spend it; one who finds
 * out by being refused has already lost the decision.
 */
export function AllowanceMeter({ entitlement, kind }: AllowanceMeterProps) {
  if (entitlement.is_paid) return null;

  const { usage } = entitlement;
  // The API already floors the remainder at zero; the limit is read straight through, so a
  // remainder can never exceed it and the meter cannot report more left than exists.
  const limit = kind === 'practice' ? usage.practice_sessions_limit : usage.daily_grade_limit;
  const remaining = Math.min(
    kind === 'practice' ? usage.practice_sessions_remaining : usage.grades_remaining_today,
    limit,
  );
  const exhausted = remaining === 0;

  const noun = kind === 'practice' ? 'practice set' : 'graded answer';
  const label = exhausted
    ? kind === 'practice'
      ? 'You have used every free practice set.'
      : 'You have used every graded answer for today.'
    : `${remaining} of ${limit} free ${noun}${remaining === 1 ? '' : 's'} left${
        kind === 'grading' ? ' today' : ''
      }.`;

  return (
    <p className="tabular text-xs text-text-muted">
      {label}{' '}
      <Link href="/pricing" className="text-accent hover:underline">
        {exhausted ? 'See plans' : 'Upgrade'}
      </Link>
    </p>
  );
}
