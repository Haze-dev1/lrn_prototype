import type { Metadata } from 'next';
import Link from 'next/link';
import { redirect } from 'next/navigation';

import { AuthShell } from '@/features/auth/components/AuthShell';
import { GoogleSignInButton } from '@/features/auth/components/GoogleSignInButton';
import { SignUpForm } from '@/features/auth/components/SignUpForm';
import { fetchAuthConfig } from '@/lib/api/auth';
import { getCurrentUser } from '@/lib/auth/session';

// Rendered per request, never prerendered: the page depends on the caller's session, and the
// build has no session (and no reachable API) to render against.
export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'Create an account' };

export default async function SignUpPage() {
  const user = await getCurrentUser();
  if (user) {
    redirect(user.onboarding_complete ? '/dashboard' : '/onboarding');
  }

  const authConfig = await fetchAuthConfig();

  return (
    <AuthShell
      title="Create your account"
      subtitle="Find out where you actually stand before an interviewer does."
      footer={
        <>
          Already have an account?{' '}
          <Link href="/signin" className="text-accent underline-offset-4 hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      {authConfig.google_enabled && authConfig.google_client_id ? (
        <GoogleSignInButton clientId={authConfig.google_client_id} text="signup_with" />
      ) : null}
      <SignUpForm />
    </AuthShell>
  );
}
