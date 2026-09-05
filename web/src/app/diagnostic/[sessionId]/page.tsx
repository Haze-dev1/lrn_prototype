import type { Metadata } from 'next';
import { notFound, redirect } from 'next/navigation';
import type { Route } from 'next';

import { SessionExit } from '@/components/layout/SessionExit';
import { DiagnosticRunner } from '@/features/diagnostic/components/DiagnosticRunner';
import { ApiError } from '@/lib/api/client';
import { fetchSession } from '@/lib/api/sessions';
import { requireOnboardedUser } from '@/lib/auth/session';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'Diagnostic' };

interface PageProps {
  params: Promise<{ sessionId: string }>;
}

/**
 * The assessment itself.
 *
 * Rendered without the application shell on purpose. The sidebar, the account link and the
 * navigation are all invitations to leave, and this is the one surface in the product where the
 * student should have nothing to look at but the question in front of them.
 */
export default async function DiagnosticSessionPage({ params }: PageProps) {
  const { sessionId } = await params;
  await requireOnboardedUser(`/diagnostic/${sessionId}`);

  const session = await fetchSession(sessionId).catch((error: unknown) => {
    // A session that does not exist and one belonging to someone else are the same 404 here as
    // they are at the API.
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  });

  if (session.status !== 'in_progress') {
    redirect(`/diagnostic/${sessionId}/results` as Route);
  }

  return (
    <main className="min-h-dvh px-6 py-10 md:py-16">
      <SessionExit kind="diagnostic" />
      <DiagnosticRunner session={session} />
    </main>
  );
}
