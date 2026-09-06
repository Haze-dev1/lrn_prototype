import type { Metadata } from 'next';
import Link from 'next/link';
import type { Route } from 'next';

import { AppShell } from '@/components/layout/AppShell';
import { Button } from '@/components/ui/Button';
import { AllowanceMeter } from '@/features/billing/components/AllowanceMeter';
import { MasteryTrend } from '@/features/progress/components/MasteryTrend';
import { ReviewList } from '@/features/review/components/ReviewList';
import { fetchEntitlement } from '@/lib/api/billing';
import { fetchProgress, fetchReview } from '@/lib/api/review';
import { fetchCurrentDiagnostic } from '@/lib/api/sessions';
import { requireOnboardedUser } from '@/lib/auth/session';
import { Activity, Target, TrendingUp, AlertCircle, ArrowRight } from 'lucide-react';

export const dynamic = 'force-dynamic';
export const metadata: Metadata = { title: 'Dashboard' };

const RECENT_COUNT = 5;

export default async function DashboardPage() {
  const user = await requireOnboardedUser('/dashboard');

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
        <main className="mx-auto w-full max-w-4xl px-6 py-12 flex flex-col gap-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
          <div>
            <p className="label-micro text-accent">Overview</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-text-primary">
              {inProgress ? 'Continue Evaluation' : 'Welcome to LRN'}
            </h1>
          </div>
          
          <section className="relative overflow-hidden rounded-[--radius-card] border border-border-strong bg-surface-1 p-8 shadow-sm">
            <div className="absolute top-0 right-0 p-8 opacity-10">
              <Target className="w-32 h-32 text-accent" />
            </div>
            
            <div className="relative z-10 max-w-xl">
              <h2 className="text-xl font-medium text-text-primary mb-3">
                Establish your baseline
              </h2>
              <p className="text-base leading-relaxed text-text-secondary mb-8">
                {inProgress
                  ? `You have answered ${inProgress.answered_count} of ${inProgress.question_count} questions. Your progress is saved securely.`
                  : 'The diagnostic takes one sitting and establishes a baseline across all eight technical categories, unlocking targeted practice.'}
              </p>
              
              <Link href={'/diagnostic' as Route}>
                <Button size="lg" className="bg-text-primary text-canvas hover:bg-text-secondary">
                  {inProgress ? 'Resume Diagnostic' : 'Take Diagnostic'}
                  <ArrowRight className="w-4 h-4 ml-2" />
                </Button>
              </Link>
            </div>
          </section>
        </main>
      </AppShell>
    );
  }

  return (
    <AppShell email={user.email} isAdmin={user.is_admin} current="/dashboard">
      <main className="mx-auto w-full max-w-5xl px-6 py-10 space-y-16 animate-in fade-in duration-700">
        <header className="flex items-end justify-between border-b border-border-subtle pb-6">
          <div>
            <p className="label-micro text-accent mb-2">OVERVIEW</p>
            <h1 className="text-3xl font-light tracking-tight text-text-primary">
              Performance Analytics
            </h1>
          </div>
          <div className="text-right hidden sm:block">
            <p className="text-sm font-medium text-text-secondary">
              {measured.length} / {progress?.total_categories ?? 8} categories evaluated
            </p>
          </div>
        </header>

        <section className="flex flex-col md:flex-row gap-12 md:gap-20 items-start">
          {/* Overall Score */}
          <div className="w-full md:w-1/3 flex flex-col gap-2">
            <p className="label-micro text-text-muted mb-2">GLOBAL MASTERY</p>
            <div className="flex items-baseline gap-3">
              <p className="tabular text-7xl font-light tracking-tight text-text-primary">
                {progress?.overall ?? '—'}
              </p>
              <span className="text-xl text-text-muted font-light">/ 100</span>
            </div>
            {progress ? (
              <div className="h-12 w-full mt-2">
                <MasteryTrend trend={progress.trend} movement={progress.movement} sparklineOnly />
              </div>
            ) : null}
          </div>

          <div className="hidden md:block w-[1px] self-stretch bg-border-subtle" />

          {/* Priority Area */}
          <div className="w-full md:flex-1 flex flex-col gap-6">
            <div>
              <p className="label-micro text-accent mb-2">PRIORITY AREA</p>
              <div className="flex items-baseline gap-4 mb-2">
                <h2 className="text-3xl font-medium tracking-tight text-text-primary">
                  {weakest.name}
                </h2>
                <span className="tabular font-mono text-lg text-text-muted">{weakest.score} / 100</span>
              </div>
              <p className="text-base text-text-secondary max-w-xl leading-relaxed">
                Your weakest category. Targeted practice here will yield the highest ROI on your overall score.
              </p>
            </div>
            
            <div className="flex items-center gap-4">
              <Link href={`/practice?category=${weakest.slug}` as Route}>
                <Button size="lg" className="bg-text-primary text-canvas hover:bg-text-secondary rounded-full px-8 shadow-sm">
                  Practice {weakest.name}
                  <ArrowRight className="w-4 h-4 ml-2" />
                </Button>
              </Link>
              {entitlement ? (
                <div className="opacity-80">
                  <AllowanceMeter entitlement={entitlement} kind="practice" />
                </div>
              ) : null}
            </div>
          </div>
        </section>

        {progress && progress.movement !== null ? (
          <section className="pt-8 border-t border-border-subtle">
            <div className="flex items-center gap-2 mb-6">
              <TrendingUp className="w-4 h-4 text-text-muted" />
              <h2 className="label-micro">MASTERY TREND</h2>
            </div>
            <div className="h-32">
              <MasteryTrend trend={progress.trend} movement={progress.movement} />
            </div>
          </section>
        ) : null}

        {recent && recent.items.length > 0 ? (
          <section aria-labelledby="recent-heading" className="space-y-6 pt-12 border-t border-border-subtle">
            <div className="flex items-baseline justify-between">
              <h2 id="recent-heading" className="text-lg font-medium tracking-tight text-text-primary">
                Recent Evaluations
              </h2>
              <Link
                href={'/review' as Route}
                className="text-sm font-medium text-text-secondary hover:text-text-primary transition-colors flex items-center gap-1"
              >
                View all history <ArrowRight className="w-3 h-3" />
              </Link>
            </div>
            <ReviewList items={recent.items} filtered={false} />
          </section>
        ) : null}
      </main>
    </AppShell>
  );
}
