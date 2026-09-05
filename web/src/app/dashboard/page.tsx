import type { Metadata } from 'next';
import Link from 'next/link';
import type { Route } from 'next';

import { AppShell } from '@/components/layout/AppShell';
import { Button } from '@/components/ui/Button';
import { AllowanceMeter } from '@/features/billing/components/AllowanceMeter';
import { MasteryTrend } from '@/features/progress/components/MasteryTrend';
import { ReviewList } from '@/features/review/components/ReviewList';
import { bandForScore } from '@/features/results/components/ScoreBar';
import { fetchEntitlement } from '@/lib/api/billing';
import { fetchProgress, fetchReview } from '@/lib/api/review';
import { fetchCurrentDiagnostic } from '@/lib/api/sessions';
import { requireOnboardedUser } from '@/lib/auth/session';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'Home' };

const RECENT_COUNT = 5;

/**
 * Signed-in home.
 *
 * The hierarchy is fixed and deliberate: current state, then the weakest area, then the
 * recommended action, then evidence, then history. That is the order a student needs those things
 * in, and it puts the single most useful action above the fold rather than behind a summary.
 *
 * There is no grid of KPI cards and no chart per category. Before a diagnostic has been taken the
 * page has exactly one thing to say and says only that, because a dashboard that implies data it
 * does not have is worse than one admitting the product has nothing to show yet.
 */
export default async function DashboardPage() {
  const user = await requireOnboardedUser('/dashboard');

  // Fetched together; a failure in either must not take the page down, so the call to action
  // still renders without the evidence beneath it.
  const [progress, recent, diagnostic, entitlement] = await Promise.all([
    fetchProgress().catch(() => null),
    fetchReview({ limit: RECENT_COUNT }).catch(() => null),
    fetchCurrentDiagnostic().catch(() => null),
    fetchEntitlement().catch(() => null),
  ]);

  const measured = progress?.categories.filter((category) => category.score !== null) ?? [];
  const weakest =
    measured.length > 0
      ? measured.reduce((lowest, category) =>
          (category.score ?? 0) < (lowest.score ?? 0) ? category : lowest,
        )
      : null;
  const inProgress = diagnostic?.status === 'in_progress' ? diagnostic : null;

  if (!weakest) {
    return (
      <AppShell email={user.email} isAdmin={user.is_admin} current="/dashboard">
        <main className="mx-auto w-full max-w-3xl space-y-8 px-6 py-12">
          <div>
            <p className="label-micro">Home</p>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight text-text-primary">
              {inProgress ? 'Finish your diagnostic' : 'Start here'}
            </h1>
          </div>
          <section className="rounded-[--radius-card] border border-border-strong bg-surface-1 p-6">
            <p className="max-w-xl text-sm leading-relaxed text-text-secondary">
              {inProgress
                ? `You have answered ${inProgress.answered_count} of ${inProgress.question_count} questions. Your answers are saved — pick up where you left off.`
                : 'Nothing here is measured yet. The diagnostic takes one sitting and establishes a baseline across all eight technical categories, so practice afterwards can target what is actually weak.'}
            </p>
            <div className="mt-5">
              <Link href={'/diagnostic' as Route}>
                <Button size="lg">
                  {inProgress ? 'Resume diagnostic' : 'Take the diagnostic'}
                </Button>
              </Link>
            </div>
          </section>
        </main>
      </AppShell>
    );
  }

  const band = bandForScore(weakest.score ?? 0);

  return (
    <AppShell email={user.email} isAdmin={user.is_admin} current="/dashboard">
      <main className="mx-auto w-full max-w-3xl space-y-10 px-6 py-12">
        <div>
          <p className="label-micro">Home</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight text-text-primary">
            Your readiness
          </h1>
        </div>

        {/* Current state, then the weakest area — the two facts that make the action below
            make sense. */}
        <section className="grid gap-4 sm:grid-cols-[1fr_1.4fr]">
          <div className="rounded-[--radius-card] border border-border-subtle bg-surface-1 p-5">
            <p className="label-micro">Overall</p>
            <p className="tabular mt-2 text-4xl font-semibold text-text-primary">
              {progress?.overall ?? '—'}
            </p>
            <p className="mt-2 text-xs text-text-muted">
              {measured.length} of {progress?.total_categories ?? 8} categories measured
            </p>
          </div>

          <div
            className={[
              'rounded-[--radius-card] border p-5',
              band === 'needs-work'
                ? 'border-band-needs-work/30 bg-band-needs-work/[0.06]'
                : 'border-border-subtle bg-surface-1',
            ].join(' ')}
          >
            <p className="label-micro">Weakest area</p>
            <p className="mt-2 text-lg font-medium text-text-primary">{weakest.name}</p>
            <p
              className={[
                'tabular mt-1 text-3xl font-semibold',
                band === 'strong'
                  ? 'text-band-strong'
                  : band === 'developing'
                    ? 'text-band-developing'
                    : 'text-band-needs-work',
              ].join(' ')}
            >
              {weakest.score}
            </p>
          </div>
        </section>

        {/* The recommended action. One, not a menu. */}
        <section className="flex flex-wrap items-center justify-between gap-4 rounded-[--radius-card] border border-border-strong bg-surface-1 p-6">
          <div className="min-w-0">
            <p className="label-micro">Do this next</p>
            <p className="mt-2 text-base text-text-primary">
              {weakest.name} is your weakest category at {weakest.score}. Ten questions there will
              move it further than anything else you could do today.
            </p>
          </div>
          <div className="space-y-2">
            <Link href={`/practice?category=${weakest.slug}` as Route}>
              <Button size="lg">Practise {weakest.name}</Button>
            </Link>
            {/* The allowance sits under the action it constrains, so a student learns what is
                left before spending it rather than by being refused. */}
            {entitlement ? (
              <AllowanceMeter entitlement={entitlement} kind="practice" />
            ) : null}
          </div>
        </section>

        {progress ? <MasteryTrend trend={progress.trend} movement={progress.movement} /> : null}

        {recent && recent.items.length > 0 ? (
          <section aria-labelledby="recent-heading" className="space-y-4">
            <div className="flex items-baseline justify-between">
              <h2 id="recent-heading" className="label-micro">
                Recent answers
              </h2>
              <Link
                href={'/review' as Route}
                className="text-sm text-accent underline-offset-4 hover:underline"
              >
                All history
              </Link>
            </div>
            <ReviewList items={recent.items} filtered={false} />
          </section>
        ) : null}
      </main>
    </AppShell>
  );
}
