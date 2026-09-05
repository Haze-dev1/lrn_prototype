import type { Metadata } from 'next';
import Link from 'next/link';
import type { Route } from 'next';
import { notFound, redirect } from 'next/navigation';

import { AppShell } from '@/components/layout/AppShell';
import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { CategoryBreakdown } from '@/features/results/components/CategoryBreakdown';
import { GradingProgressPanel } from '@/features/results/components/GradingProgressPanel';
import { ApiError } from '@/lib/api/client';
import { fetchResults } from '@/lib/api/sessions';
import { requireOnboardedUser } from '@/lib/auth/session';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'Practice summary' };

interface PageProps {
  params: Promise<{ sessionId: string }>;
}

export default async function PracticeSummaryPage({ params }: PageProps) {
  const { sessionId } = await params;
  const user = await requireOnboardedUser(`/practice/${sessionId}/summary`);

  const results = await fetchResults(sessionId).catch((error: unknown) => {
    if (error instanceof ApiError && error.status === 404) notFound();
    if (error instanceof ApiError && error.status === 409) {
      redirect(`/practice/${sessionId}` as Route);
    }
    throw error;
  });

  const sessionScores = results.categories.flatMap((category) => category.session_scores);
  const setAverage =
    sessionScores.length === 0
      ? null
      : Math.round(sessionScores.reduce((total, score) => total + score, 0) / sessionScores.length);

  return (
    <AppShell email={user.email} isAdmin={user.is_admin} current="/practice">
      <main className="mx-auto w-full max-w-3xl space-y-8 px-6 py-12">
        <div>
          <p className="label-micro">Practice summary</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight text-text-primary">
            {results.progress.grading_complete ? 'How that set went' : 'Grading your answers'}
          </h1>
        </div>

        {results.progress.grading_complete ? (
          <>
            {results.progress.failed > 0 ? (
              <Alert tone="info">
                {results.progress.failed} answer
                {results.progress.failed === 1 ? '' : 's'} could not be graded. They are saved and
                will be graded automatically.
              </Alert>
            ) : null}

            <section className="grid gap-4 sm:grid-cols-3">
              <div className="rounded-[--radius-card] border border-border-subtle bg-surface-1 p-5">
                <p className="label-micro">This set</p>
                <p className="tabular mt-2 text-3xl font-semibold text-text-primary">
                  {setAverage ?? '—'}
                </p>
              </div>
              <div className="rounded-[--radius-card] border border-border-subtle bg-surface-1 p-5">
                <p className="label-micro">Answered</p>
                <p className="tabular mt-2 text-3xl font-semibold text-text-primary">
                  {results.progress.graded}
                </p>
              </div>
              <div className="rounded-[--radius-card] border border-border-subtle bg-surface-1 p-5">
                <p className="label-micro">Categories</p>
                <p className="tabular mt-2 text-3xl font-semibold text-text-primary">
                  {results.categories.length}
                </p>
              </div>
            </section>

            {/* Category mastery, not this set's mean. A ten-question set moves a recency-weighted
                score a little; showing the set's own average as if it were readiness would let a
                good run read as mastery the student has not earned. */}
            <CategoryBreakdown categories={results.categories} />

            <div className="flex flex-wrap items-center gap-4 border-t border-border-subtle pt-6">
              <Link href={'/practice' as Route}>
                <Button size="lg">Practise again</Button>
              </Link>
              <Link
                href={'/dashboard' as Route}
                className="text-sm text-accent underline-offset-4 hover:underline"
              >
                Back to your dashboard
              </Link>
            </div>
          </>
        ) : (
          <GradingProgressPanel sessionId={sessionId} initial={results} />
        )}
      </main>
    </AppShell>
  );
}
