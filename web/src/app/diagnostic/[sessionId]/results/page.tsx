import type { Metadata } from 'next';
import Link from 'next/link';
import type { Route } from 'next';
import { notFound, redirect } from 'next/navigation';

import { AppShell } from '@/components/layout/AppShell';
import { Alert } from '@/components/ui/Alert';
import { UpgradePrompt } from '@/features/billing/components/UpgradePrompt';
import { CategoryBreakdown } from '@/features/results/components/CategoryBreakdown';
import { GradingProgressPanel } from '@/features/results/components/GradingProgressPanel';
import { ResultsHeadline } from '@/features/results/components/ResultsHeadline';
import { fetchEntitlement } from '@/lib/api/billing';
import { ApiError } from '@/lib/api/client';
import { fetchResults } from '@/lib/api/sessions';
import { requireOnboardedUser } from '@/lib/auth/session';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'Diagnostic results' };

interface PageProps {
  params: Promise<{ sessionId: string }>;
}

export default async function DiagnosticResultsPage({ params }: PageProps) {
  const { sessionId } = await params;
  const user = await requireOnboardedUser(`/diagnostic/${sessionId}/results`);

  const results = await fetchResults(sessionId).catch((error: unknown) => {
    if (error instanceof ApiError && error.status === 404) notFound();
    // The session is still open, so there is nothing to report yet; send the student back to it
    // rather than showing an error for a state that is not an error.
    if (error instanceof ApiError && error.status === 409) {
      redirect(`/diagnostic/${sessionId}` as Route);
    }
    throw error;
  });

  const entitlement = await fetchEntitlement();
  const failed = results.progress.failed;

  return (
    <AppShell email={user.email} isAdmin={user.is_admin} current="/diagnostic">
      <main className="mx-auto w-full max-w-3xl space-y-8 px-6 py-12">
        <div>
          <p className="label-micro">Diagnostic results</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight text-text-primary">
            {results.progress.grading_complete
              ? 'Where you stand today'
              : 'Grading your answers'}
          </h1>
        </div>

        {results.progress.grading_complete ? (
          <>
            {failed > 0 ? (
              <Alert tone="info">
                {failed} answer{failed === 1 ? '' : 's'} could not be graded. Your{' '}
                {failed === 1 ? 'answer is' : 'answers are'} saved and the scores below are based
                on the {results.progress.graded} that were graded.
              </Alert>
            ) : null}

            <ResultsHeadline
              categories={results.categories}
              recommendation={results.recommendation}
            />
            <CategoryBreakdown categories={results.categories} />
            <UpgradePrompt entitlement={entitlement} categories={results.categories} />

            <div className="flex flex-wrap gap-4 border-t border-border-subtle pt-6 text-sm">
              <Link
                href={'/dashboard' as Route}
                className="text-accent underline-offset-4 hover:underline"
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
