import type { Metadata } from 'next';
import Link from 'next/link';
import type { Route } from 'next';

import { AppShell } from '@/components/layout/AppShell';
import { ReviewFilters } from '@/features/review/components/ReviewFilters';
import { ReviewList } from '@/features/review/components/ReviewList';
import { fetchCategories } from '@/lib/api/questions';
import { fetchReview, type ReviewFilters as Filters } from '@/lib/api/review';
import { requireOnboardedUser } from '@/lib/auth/session';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'Review' };

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

/** Read one search parameter as a string, ignoring repeated values. */
function one(
  params: Record<string, string | string[] | undefined>,
  key: string,
): string | undefined {
  const value = params[key];
  return Array.isArray(value) ? value[0] : value;
}

export default async function ReviewPage({ searchParams }: PageProps) {
  const user = await requireOnboardedUser('/review');
  const params = await searchParams;

  const maxScore = Number(one(params, 'max_score'));
  const filters: Filters = {
    category_slug: one(params, 'category_slug'),
    // A non-numeric value in the URL is dropped rather than sent, so a hand-edited query string
    // produces an unfiltered list instead of a validation error page.
    max_score: Number.isInteger(maxScore) && maxScore >= 0 && maxScore <= 100 ? maxScore : undefined,
    missed_concept: one(params, 'missed_concept'),
    flagged_only: one(params, 'flagged_only') === 'true',
    recent_only: one(params, 'recent_only') === 'true',
    before: one(params, 'before'),
    limit: 20,
  };

  const [categories, page] = await Promise.all([fetchCategories(), fetchReview(filters)]);

  const nextQuery = new URLSearchParams(
    Object.entries(params).flatMap(([key, value]) =>
      typeof value === 'string' && key !== 'before' ? [[key, value] as [string, string]] : [],
    ),
  );
  if (page.next_cursor) nextQuery.set('before', page.next_cursor);

  const filtered = ['category_slug', 'max_score', 'flagged_only', 'recent_only', 'missed_concept'].some(
    (key) => key in params,
  );

  return (
    <AppShell email={user.email} isAdmin={user.is_admin} current="/review">
      <main className="mx-auto w-full max-w-3xl space-y-6 px-6 py-12">
        <div>
          <p className="label-micro">Review</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight text-text-primary">
            Everything you have answered
          </h1>
          {one(params, 'missed_concept') ? (
            <p className="mt-3 text-sm text-text-secondary">
              Showing answers that missed{' '}
              <span className="font-mono text-xs">{one(params, 'missed_concept')}</span>.
            </p>
          ) : null}
        </div>

        <ReviewFilters categories={categories} />
        <ReviewList items={page.items} filtered={filtered} />

        {page.next_cursor ? (
          <div className="flex justify-center">
            <Link
              href={`/review?${nextQuery.toString()}` as Route}
              className="text-sm text-accent underline-offset-4 hover:underline"
            >
              Older answers
            </Link>
          </div>
        ) : null}
      </main>
    </AppShell>
  );
}
