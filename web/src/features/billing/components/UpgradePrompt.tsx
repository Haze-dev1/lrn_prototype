import Link from 'next/link';

import type { Entitlement } from '@/lib/api/billing';
import type { CategoryResult } from '@/lib/api/sessions';

export interface UpgradePromptProps {
  entitlement: Entitlement;
  /** The measured categories, used to name what the student would actually be working on. */
  categories: CategoryResult[];
}

/**
 * The conversion block on the results page.
 *
 * Placed after the results, never before them, because the argument only works once a student has
 * seen a number they do not like. Selling access before that is asking someone to buy a solution
 * to a problem they have not been shown they have.
 *
 * It names their weakest category and counts their actual missed concepts. Generic pricing copy
 * would be easier to write and would say nothing this student could not have read before taking
 * the diagnostic — the specificity is the entire point, and it is only possible here because the
 * evidence is already on the page.
 *
 * Renders nothing for a paid account.
 */
export function UpgradePrompt({ entitlement, categories }: UpgradePromptProps) {
  if (entitlement.is_paid) return null;

  const measured = categories.filter((category) => category.evidence_count > 0);
  const weakest = measured.reduce<CategoryResult | null>(
    (worst, category) => (worst === null || category.score < worst.score ? category : worst),
    null,
  );
  const missedConcepts = measured.reduce(
    (total, category) => total + category.missed_concepts.length,
    0,
  );

  return (
    <section className="rounded-[--radius-card] border border-accent-muted bg-surface-2 p-6">
      <p className="label-micro text-accent">Next</p>
      <h2 className="mt-2.5 text-xl font-semibold tracking-tight text-text-primary">
        You found the gaps. Now close them.
      </h2>

      <p className="mt-3 text-sm leading-relaxed text-text-secondary">
        {weakest ? (
          <>
            {weakest.name} is your weakest category at {weakest.score}
            {missedConcepts > 0 ? (
              <>
                , and there {missedConcepts === 1 ? 'is' : 'are'} {missedConcepts} concept
                {missedConcepts === 1 ? '' : 's'} you missed across this sitting
              </>
            ) : null}
            . Paid access is adaptive practice that keeps bringing those back — on a schedule, at
            the right difficulty — until you stop missing them.
          </>
        ) : (
          <>
            Paid access is adaptive practice that keeps bringing back what you missed, on a
            schedule and at the right difficulty, until you stop missing it.
          </>
        )}
      </p>

      <p className="tabular mt-3 text-xs text-text-muted">
        You have {entitlement.usage.practice_sessions_remaining} of{' '}
        {entitlement.usage.practice_sessions_limit} free practice sets left.
      </p>

      <div className="mt-5 flex flex-wrap gap-3">
        <Link
          href="/pricing"
          className="inline-flex h-10 items-center justify-center rounded-md bg-text-primary px-4 text-sm font-medium text-text-inverse transition-colors hover:bg-white"
        >
          See plans
        </Link>
        {entitlement.can_start_practice ? (
          <Link
            href="/practice"
            className="inline-flex h-10 items-center justify-center rounded-md border border-border-subtle px-4 text-sm text-text-secondary transition-colors hover:border-border-strong hover:text-text-primary"
          >
            Use a free set first
          </Link>
        ) : null}
      </div>
    </section>
  );
}
