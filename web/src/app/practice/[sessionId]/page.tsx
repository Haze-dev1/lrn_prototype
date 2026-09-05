import type { Metadata } from 'next';
import { notFound, redirect } from 'next/navigation';
import type { Route } from 'next';

import { SessionExit } from '@/components/layout/SessionExit';
import { PracticeRunner } from '@/features/practice/components/PracticeRunner';
import { ApiError } from '@/lib/api/client';
import { fetchSession } from '@/lib/api/sessions';
import { requireOnboardedUser } from '@/lib/auth/session';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'Practice' };

interface PageProps {
  params: Promise<{ sessionId: string }>;
}

/** The practice session. Rendered without the shell, for the same reason the diagnostic is. */
export default async function PracticeSessionPage({ params }: PageProps) {
  const { sessionId } = await params;
  await requireOnboardedUser(`/practice/${sessionId}`);

  const session = await fetchSession(sessionId).catch((error: unknown) => {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  });

  if (session.status !== 'in_progress') {
    redirect(`/practice/${sessionId}/summary` as Route);
  }

  return (
    <main className="min-h-dvh px-6 py-10 md:py-16">
      <SessionExit kind="practice" />
      {session.selection_rationale ? (
        <p className="mx-auto mb-8 w-full max-w-3xl text-sm text-text-muted">
          {session.selection_rationale.explanation}
        </p>
      ) : null}
      <PracticeRunner session={session} />
    </main>
  );
}
