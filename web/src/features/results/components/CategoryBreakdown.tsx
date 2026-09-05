import { Badge } from '@/components/ui/Badge';
import { ScoreBar, bandForScore } from '@/features/results/components/ScoreBar';
import type { CategoryResult } from '@/lib/api/sessions';

const BAND_LABEL: Record<string, string> = {
  strong: 'Strong',
  developing: 'Developing',
  'needs-work': 'Needs work',
};

export interface CategoryBreakdownProps {
  categories: CategoryResult[];
}

/**
 * Every category, weakest first.
 *
 * Ordering by score rather than by the taxonomy's display order is the point: the thing a student
 * needs to act on is at the top, and they do not have to scan eight rows to find it. Missed
 * concepts are listed per category because "you scored 54" is a verdict while "you missed the net
 * debt bridge and the treatment of cash" is something to go and fix.
 */
export function CategoryBreakdown({ categories }: CategoryBreakdownProps) {
  const ranked = [...categories].sort((a, b) => a.score - b.score);

  return (
    <section aria-labelledby="breakdown-heading" className="space-y-4">
      <h2 id="breakdown-heading" className="label-micro">
        Every category, weakest first
      </h2>

      <ul className="divide-y divide-border-subtle rounded-[--radius-card] border border-border-subtle">
        {ranked.map((category) => {
          const band = bandForScore(category.score);
          const movement =
            category.previous_score === null ? null : category.score - category.previous_score;

          return (
            <li key={category.slug} className="space-y-3 px-5 py-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-sm font-medium text-text-primary">{category.name}</h3>
                <div className="flex items-center gap-2">
                  {movement !== null && movement !== 0 ? (
                    <span className="tabular text-xs text-text-muted">
                      {movement > 0 ? '+' : ''}
                      {movement}
                    </span>
                  ) : null}
                  <Badge tone={band}>{BAND_LABEL[band]}</Badge>
                </div>
              </div>

              <ScoreBar score={category.score} label={category.name} />

              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-muted">
                {/* "This session", not "This diagnostic": the same breakdown renders on the
                    practice summary, where naming it a diagnostic is simply untrue. */}
                <span className="tabular">
                  This session: {category.session_scores.join(' · ')}
                </span>
                {/* An empty missed list is not evidence of full coverage. A grading failure,
                    or a model response whose concept keys were all rejected, also produces an
                    empty list — and "Full concept coverage" beside a score of 0 is a
                    contradiction the student would be right not to trust. The claim is only made
                    where the score supports it; otherwise nothing is said. */}
                {category.missed_concepts.length > 0 ? (
                  <span>
                    {category.missed_concepts.length} concept
                    {category.missed_concepts.length === 1 ? '' : 's'} missed
                  </span>
                ) : band === 'strong' ? (
                  <span className="text-band-strong">Full concept coverage</span>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
