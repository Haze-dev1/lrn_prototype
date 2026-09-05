import Link from 'next/link';
import type { Route } from 'next';

import { Button } from '@/components/ui/Button';
import { bandForScore } from '@/features/results/components/ScoreBar';
import type { CategoryResult, Recommendation } from '@/lib/api/sessions';

export interface ResultsHeadlineProps {
  categories: CategoryResult[];
  recommendation: Recommendation | null;
}

/**
 * The answer to "where am I, and what do I do now".
 *
 * Weakest area first and largest, strongest second and smaller. That ordering is deliberate: a
 * results page that leads with what you are good at is flattering and useless, and the student is
 * here to find out what to fix. The recommendation is a single action with a plain-language
 * reason, not a menu.
 */
export function ResultsHeadline({ categories, recommendation }: ResultsHeadlineProps) {
  const ranked = [...categories].sort((a, b) => a.score - b.score);
  const weakest = ranked[0];
  const strongest = ranked[ranked.length - 1];
  // Guards the empty case and narrows both ends for the type checker in one step.
  if (!weakest || !strongest) return null;
  const overall = Math.round(
    categories.reduce((total, category) => total + category.score, 0) / categories.length,
  );

  return (
    <section aria-labelledby="headline-heading" className="space-y-6">
      <h2 id="headline-heading" className="sr-only">
        Summary
      </h2>

      <div className="grid gap-4 md:grid-cols-[1.6fr_1fr]">
        <div className="rounded-[--radius-card] border border-band-needs-work/30 bg-band-needs-work/[0.06] p-6">
          <p className="label-micro">Weakest area</p>
          <p className="mt-3 text-2xl font-semibold tracking-tight text-text-primary">
            {weakest.name}
          </p>
          <p className="tabular mt-1 text-5xl font-semibold text-band-needs-work">
            {weakest.score}
          </p>
          {weakest.missed_concepts.length > 0 ? (
            <p className="mt-3 text-sm text-text-secondary">
              {weakest.missed_concepts.length} expected concept
              {weakest.missed_concepts.length === 1 ? '' : 's'} missed across{' '}
              {weakest.answered} questions.
            </p>
          ) : null}
        </div>

        <div className="grid gap-4">
          <div className="rounded-[--radius-card] border border-border-subtle bg-surface-1 p-5">
            <p className="label-micro">Strongest area</p>
            <p className="mt-2 text-sm font-medium text-text-primary">{strongest.name}</p>
            <p className="tabular mt-1 text-2xl font-semibold text-band-strong">
              {strongest.score}
            </p>
          </div>
          <div className="rounded-[--radius-card] border border-border-subtle bg-surface-1 p-5">
            <p className="label-micro">Across all eight</p>
            <p
              className={[
                'tabular mt-2 text-2xl font-semibold',
                bandForScore(overall) === 'strong'
                  ? 'text-band-strong'
                  : bandForScore(overall) === 'developing'
                    ? 'text-band-developing'
                    : 'text-band-needs-work',
              ].join(' ')}
            >
              {overall}
            </p>
          </div>
        </div>
      </div>

      {recommendation ? (
        <div className="flex flex-wrap items-center justify-between gap-4 rounded-[--radius-card] border border-border-strong bg-surface-1 p-6">
          <div className="min-w-0">
            <p className="label-micro">Do this next</p>
            <p className="mt-2 text-base text-text-primary">{recommendation.reason}</p>
          </div>
          <Link href={`/practice?category=${recommendation.category_slug}` as Route}>
            <Button size="lg">Practise {recommendation.category_name}</Button>
          </Link>
        </div>
      ) : null}
    </section>
  );
}
