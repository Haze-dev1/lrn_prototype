import type { Metadata } from 'next';
import Link from 'next/link';
import { redirect } from 'next/navigation';

import { AuthShell } from '@/features/auth/components/AuthShell';
import { GoogleSignInButton } from '@/features/auth/components/GoogleSignInButton';
import { SignInForm } from '@/features/auth/components/SignInForm';
import { fetchAuthConfig } from '@/lib/api/auth';
import { getCurrentUser } from '@/lib/auth/session';

// Rendered per request, never prerendered: the page depends on the caller's session, and the
// build has no session (and no reachable API) to render against.
export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'Sign in' };

export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const user = await getCurrentUser();
  if (user) {
    redirect(user.onboarding_complete ? '/dashboard' : '/onboarding');
  }

  const { next } = await searchParams;
  // Read from the API rather than the bundle, so the client ID the browser uses is always the
  // one the server verifies against. A deployment without Google configured renders nothing.
  const authConfig = await fetchAuthConfig();

  return (
    <AuthShell
      title="Sign in"
      subtitle="Pick up where you left off."
      footer={
        <>
          New to LRN?{' '}
          <Link href="/signup" className="text-accent underline-offset-4 hover:underline">
            Create an account
          </Link>
        </>
      }
    >
      {authConfig.google_enabled && authConfig.google_client_id ? (
        <GoogleSignInButton clientId={authConfig.google_client_id} nextPath={next} />
      ) : null}
      <SignInForm nextPath={next} />
    </AuthShell>
  );
}
