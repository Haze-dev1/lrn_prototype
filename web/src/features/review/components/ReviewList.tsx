import Link from 'next/link';
import type { Route } from 'next';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import type { Band } from '@/lib/api/sessions';
import type { ReviewItem } from '@/lib/api/review';

const BAND_TONE: Record<Band, BadgeTone> = {
  strong: 'strong',
  developing: 'developing',
  needs_work: 'needs-work',
};

const SCORE_COLOUR: Record<Band, string> = {
  strong: 'text-band-strong',
  developing: 'text-band-developing',
  needs_work: 'text-band-needs-work',
};

export interface ReviewListProps {
  items: ReviewItem[];
  /** Copy for the empty state, which differs when filters are applied. */
  filtered: boolean;
}

/**
 * Past answers, newest first.
 *
 * The score leads each row because it is what a student scans for. The prompt is truncated to two
 * lines: this is an index, and a wall of full question text would make it unscannable.
 */
export function ReviewList({ items, filtered }: ReviewListProps) {
  if (items.length === 0) {
    return (
      <div className="rounded-[--radius-card] border border-dashed border-border-subtle px-6 py-14 text-center">
        <p className="text-sm text-text-secondary">
          {filtered ? 'No answers match these filters.' : 'Nothing to review yet.'}
        </p>
        <p className="mt-1 text-sm text-text-muted">
          {filtered
            ? 'Clear the filters to see your full history.'
            : 'Every answer you submit appears here once it has been graded.'}
        </p>
      </div>
    );
  }

  return (
    <ul className="divide-y divide-border-subtle rounded-[--radius-card] border border-border-subtle">
      {items.map((item) => (
        <li key={item.id}>
          <Link
            href={`/review/${item.id}` as Route}
            className="flex gap-5 px-5 py-4 transition-colors hover:bg-surface-1"
          >
            <span
              className={`tabular w-10 shrink-0 text-2xl font-semibold ${SCORE_COLOUR[item.band]}`}
            >
              {item.score}
            </span>

            <span className="min-w-0 flex-1">
              <span className="flex flex-wrap items-center gap-2">
                <span className="label-micro">{item.category_name}</span>
                {item.flagged ? <Badge tone="developing">Flagged</Badge> : null}
              </span>
              <span className="mt-1 line-clamp-2 block text-sm text-text-primary">
                {item.prompt}
              </span>
              {item.concepts_missed.length > 0 ? (
                <span className="mt-1 block text-xs text-text-muted">
                  {item.concepts_missed.length} concept
                  {item.concepts_missed.length === 1 ? '' : 's'} missed
                </span>
              ) : null}
            </span>

            <span className="hidden shrink-0 self-center sm:block">
              <Badge tone={BAND_TONE[item.band]}>{item.band.replace('_', ' ')}</Badge>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
