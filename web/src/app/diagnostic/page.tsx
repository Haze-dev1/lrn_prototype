import type { Metadata } from 'next';
import Link from 'next/link';
import type { Route } from 'next';

import { AppShell } from '@/components/layout/AppShell';
import { StartDiagnosticButton } from '@/features/diagnostic/components/StartDiagnosticButton';
import { fetchCurrentDiagnostic } from '@/lib/api/sessions';
import { requireOnboardedUser } from '@/lib/auth/session';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'Diagnostic' };

const WHAT_TO_EXPECT = [
  '24 questions, three from each of the eight technical categories.',
  'Written answers, the way you would give them out loud in an interview.',
  'Difficulty rises as you go. Later questions are meant to be hard.',
  'Every answer is graded against the same rubric an interviewer would use.',
];

export default async function DiagnosticIntroPage() {
  const user = await requireOnboardedUser('/diagnostic');
  const existing = await fetchCurrentDiagnostic();

  const inProgress = existing?.status === 'in_progress' ? existing : null;
  const finished = existing?.status === 'completed' ? existing : null;

  return (
    <AppShell email={user.email} isAdmin={user.is_admin} current="/diagnostic">
      <main className="mx-auto w-full max-w-2xl space-y-8 px-6 py-14">
        <div>
          <p className="label-micro">Diagnostic</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight text-text-primary">
            {inProgress
              ? 'Pick up where you left off'
              : finished
                ? 'Take the diagnostic again'
                : 'Find out where you actually stand'}
          </h1>
          <p className="mt-3 text-text-secondary">
            {inProgress
              ? `You have answered ${inProgress.answered_count} of ${inProgress.question_count}. Your answers are saved.`
              : 'One sitting establishes a baseline across all eight categories, so every practice session afterwards can target what is actually weak.'}
          </p>
        </div>

        <ul className="space-y-3 rounded-[--radius-card] border border-border-subtle bg-surface-1 p-6">
          {WHAT_TO_EXPECT.map((item) => (
            <li key={item} className="flex gap-3 text-sm text-text-secondary">
              <span aria-hidden="true" className="mt-2 h-1 w-1 shrink-0 rounded-full bg-accent" />
              {item}
            </li>
          ))}
        </ul>

        <div className="flex flex-wrap items-center gap-4">
          <StartDiagnosticButton
            label={inProgress ? 'Resume diagnostic' : finished ? 'Start a new diagnostic' : 'Begin the diagnostic'}
          />
          {finished ? (
            <Link
              href={`/diagnostic/${finished.id}/results` as Route}
              className="text-sm text-accent underline-offset-4 hover:underline"
            >
              See your last results
            </Link>
          ) : null}
        </div>

        <p className="text-xs text-text-muted">
          There is no timer. You can stop and come back — answers are saved as you submit them.
        </p>
      </main>
    </AppShell>
  );
}
