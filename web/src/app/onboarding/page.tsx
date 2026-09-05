import type { Metadata } from 'next';

import { OnboardingForm } from '@/features/onboarding/components/OnboardingForm';
import { requireUser } from '@/lib/auth/session';

// Rendered per request, never prerendered: the page depends on the caller's session, and the
// build has no session (and no reachable API) to render against.
export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'Set up your account' };

export default async function OnboardingPage() {
  const user = await requireUser('/onboarding');

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center gap-8 px-6 py-16">
      <div className="space-y-3">
        <p className="label-micro">Step 1 of 1</p>
        <h1 className="text-2xl font-semibold tracking-tight text-text-primary">
          Tell us where you are
        </h1>
        <p className="text-sm leading-relaxed text-text-secondary">
          Three questions, then you can start. This shapes which questions you see and how your
          readiness is measured.
        </p>
      </div>

      <div className="rounded-[--radius-card] border border-border-subtle bg-surface-1 p-6">
        <OnboardingForm profile={user.profile} />
      </div>
    </main>
  );
}
