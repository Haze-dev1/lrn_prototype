import Link from 'next/link';

import { ManageBillingButton } from '@/features/billing/components/ManageBillingButton';
import type { Entitlement } from '@/lib/api/billing';

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
}

const PLAN_NAMES: Record<Entitlement['plan'], string> = {
  free: 'Free',
  pro_monthly: 'Pro',
  season_pass: 'Season Pass',
};

/**
 * The billing section of the account page.
 *
 * Four states, all of them explicit: never paid, paying, cancelling at the period end, and
 * expired. The expired state names the date and offers renewal rather than showing a generic
 * upgrade prompt — someone who has already paid once is owed the difference between "your access
 * ended" and "here is what this costs".
 *
 * All of it is read from the server's entitlement. Nothing here is derived locally, so this panel
 * cannot disagree with what the API will actually allow.
 */
export function BillingPanel({ entitlement }: { entitlement: Entitlement }) {
  const { usage } = entitlement;

  return (
    <section className="rounded-[--radius-card] border border-border-subtle bg-surface-1 p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <p className="label-micro">Plan</p>
          <h2 className="mt-2 text-lg font-semibold text-text-primary">
            {PLAN_NAMES[entitlement.plan]}
          </h2>
        </div>
        {entitlement.is_paid ? (
          <span className="label-micro text-band-strong">Active</span>
        ) : null}
      </div>

      {entitlement.is_paid ? (
        <p className="mt-3 text-sm leading-relaxed text-text-secondary">
          {entitlement.cancel_at_period_end && entitlement.active_until
            ? `Your plan is set to end on ${formatDate(entitlement.active_until)}. You keep full access until then.`
            : entitlement.active_until
              ? `Access runs until ${formatDate(entitlement.active_until)}.`
              : 'Your subscription renews automatically. Cancel any time.'}
        </p>
      ) : entitlement.expired_at ? (
        <p className="mt-3 text-sm leading-relaxed text-text-secondary">
          Your access ended on {formatDate(entitlement.expired_at)}. Everything you answered is
          still here — your history, your mastery and your review are unchanged.
        </p>
      ) : (
        <div className="mt-3 space-y-2 text-sm leading-relaxed text-text-secondary">
          <p>
            You are on the free tier. The diagnostic is fully graded; practice and daily grading
            are limited.
          </p>
          <p className="tabular text-xs text-text-muted">
            {usage.practice_sessions_remaining} of {usage.practice_sessions_limit} practice sets
            left · {usage.grades_remaining_today} of {usage.daily_grade_limit} graded answers left
            today
          </p>
        </div>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-3">
        {entitlement.can_manage_billing ? <ManageBillingButton /> : null}
        {!entitlement.is_paid ? (
          <Link
            href="/pricing"
            className="inline-flex h-10 items-center justify-center rounded-md bg-text-primary px-4 text-sm font-medium text-text-inverse transition-colors hover:bg-white"
          >
            {entitlement.expired_at ? 'Renew access' : 'See plans'}
          </Link>
        ) : null}
      </div>
    </section>
  );
}
