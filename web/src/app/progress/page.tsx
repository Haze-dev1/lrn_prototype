import type { Metadata } from 'next';
import Link from 'next/link';
import type { Route } from 'next';

import { TrendingUp } from 'lucide-react';

import { AppShell } from '@/components/layout/AppShell';
import { Button } from '@/components/ui/Button';
import { CategoryProgressList } from '@/features/progress/components/CategoryProgressList';
import { MasteryTrend } from '@/features/progress/components/MasteryTrend';
import { fetchProgress } from '@/lib/api/review';
import { requireOnboardedUser } from '@/lib/auth/session';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'Progress' };

export default async function ProgressPage() {
  const user = await requireOnboardedUser('/progress');
  const progress = await fetchProgress();

  const hasEvidence = progress.measured_categories > 0;

  return (
    <AppShell email={user.email} isAdmin={user.is_admin} current="/progress">
      <main className="mx-auto w-full max-w-3xl space-y-8 px-6 py-12">
        <div>
          <p className="label-micro">Progress</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight text-text-primary">
            {hasEvidence ? 'Where you stand' : 'Nothing measured yet'}
          </h1>
          {hasEvidence ? (
            <p className="mt-3 text-sm text-text-secondary">
              {progress.measured_categories} of {progress.total_categories} categories measured,
              from {progress.total_evidence} graded answer
              {progress.total_evidence === 1 ? '' : 's'}.
            </p>
          ) : (
            <p className="mt-3 max-w-xl text-sm leading-relaxed text-text-secondary">
              Mastery is only shown where there is graded evidence behind it. Take the diagnostic
              to establish a baseline across all eight categories.
            </p>
          )}
        </div>

        {hasEvidence ? (
          <div className="space-y-16">
            <section aria-labelledby="trend-heading" className="pt-8 border-t border-border-subtle">
              <div className="flex items-center gap-2 mb-6">
                <TrendingUp className="w-4 h-4 text-text-muted" aria-hidden="true" />
                <h2 id="trend-heading" className="label-micro text-accent">
                  MASTERY TREND
                </h2>
              </div>
              <div className="h-40">
                <MasteryTrend trend={progress.trend} movement={progress.movement} />
              </div>
            </section>
            
            <section>
              <h2 className="label-micro text-accent mb-6">CATEGORY BREAKDOWN</h2>
              <CategoryProgressList categories={progress.categories} />
            </section>
          </div>
        ) : (
          <Link href={'/diagnostic' as Route}>
            <Button size="lg">Take the diagnostic</Button>
          </Link>
        )}
      </main>
    </AppShell>
  );
}
