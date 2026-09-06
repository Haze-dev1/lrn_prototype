import type { Metadata } from 'next';

import { AppShell } from '@/components/layout/AppShell';
import { GlossaryClient } from '@/features/glossary/components/GlossaryClient';
import { PublicShell } from '@/features/marketing/components/PublicShell';
import { getCurrentUser } from '@/lib/auth/session';

export const metadata: Metadata = {
  title: 'Glossary',
  description:
    'Plain-language definitions of the finance terms that come up in banking and private equity technical interviews.',
};

// The signed-in render shows the app shell, which needs the caller's identity.
export const dynamic = 'force-dynamic';

/**
 * The financial glossary.
 *
 * Public: it is reference content, it is linked from the public navbar and footer, and it is the
 * top of the funnel. It was previously behind `requireOnboardedUser`, so every visitor who
 * clicked "Glossary" on the marketing site was bounced to sign-in — and registered users who had
 * not finished onboarding could not read it either.
 *
 * `getCurrentUser` returns null rather than redirecting, so the page picks its chrome from who is
 * asking instead of forcing a session to exist.
 */
export default async function GlossaryPage() {
  const user = await getCurrentUser();

  const content = (
    <main className="mx-auto w-full max-w-5xl px-6 py-12">
      <GlossaryClient />
    </main>
  );

  return user ? (
    <AppShell email={user.email} isAdmin={user.is_admin} current="/glossary">
      {content}
    </AppShell>
  ) : (
    <PublicShell>{content}</PublicShell>
  );
}
