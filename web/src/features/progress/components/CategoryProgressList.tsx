import Link from 'next/link';
import type { Route } from 'next';

import { Badge } from '@/components/ui/Badge';
import { ScoreBar, bandForScore } from '@/features/results/components/ScoreBar';
import type { CategoryProgress } from '@/lib/api/review';

export interface CategoryProgressListProps {
  categories: CategoryProgress[];
}

/**
 * Mastery per category, weakest first.
 *
 * A category with no evidence renders as "not measured" rather than as a zero bar. Those are
 * different claims: one says the student is weak, the other says the product does not know, and
 * showing the first when the second is true is a fabricated readiness signal.
 *
 * Every row links to practice for that category, so the page ends in doing rather than reading.
 */
export function CategoryProgressList({ categories }: CategoryProgressListProps) {
  const measured = categories.filter((category) => category.score !== null);
  const unmeasured = categories.filter((category) => category.score === null);
  const ranked = [...measured].sort((a, b) => (a.score ?? 0) - (b.score ?? 0));

  return (
    <section aria-labelledby="categories-heading" className="space-y-4">
      <h2 id="categories-heading" className="label-micro">
        Every category, weakest first
      </h2>

      <ul className="divide-y divide-border-subtle rounded-[--radius-card] border border-border-subtle">
        {ranked.map((category) => {
          const score = category.score ?? 0;
          const movement =
            category.previous_score === null ? null : score - category.previous_score;

          return (
            <li key={category.slug} className="space-y-3 px-5 py-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <Link
                  href={`/practice?category=${category.slug}` as Route}
                  className="text-sm font-medium text-text-primary underline-offset-4 hover:underline"
                >
                  {category.name}
                </Link>
                <div className="flex items-center gap-2">
                  {category.provisional ? <Badge tone="neutral">Provisional</Badge> : null}
                  {movement !== null && movement !== 0 ? (
                    <span
                      className={[
                        'tabular text-xs',
                        movement > 0 ? 'text-band-strong' : 'text-band-needs-work',
                      ].join(' ')}
                    >
                      {movement > 0 ? '+' : ''}
                      {movement}
                    </span>
                  ) : null}
                  <Badge tone={bandForScore(score)}>
                    {bandForScore(score) === 'needs-work' ? 'Needs work' : bandForScore(score)}
                  </Badge>
                </div>
              </div>

              <ScoreBar score={score} label={category.name} />

              <p className="text-xs text-text-muted">
                {category.evidence_count} graded answer
                {category.evidence_count === 1 ? '' : 's'}
                {category.provisional ? ' — still settling' : ''}
              </p>
            </li>
          );
        })}

        {unmeasured.map((category) => (
          <li
            key={category.slug}
            className="flex items-center justify-between gap-4 px-5 py-4"
          >
            <Link
              href={`/practice?category=${category.slug}` as Route}
              className="text-sm text-text-secondary underline-offset-4 hover:underline"
            >
              {category.name}
            </Link>
            {/* Not a zero. "Not measured" and "measured badly" are different claims. */}
            <span className="text-xs text-text-muted">Not measured yet</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
