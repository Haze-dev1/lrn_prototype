import type { Metadata } from 'next';
import Link from 'next/link';

import { AppShell } from '@/components/layout/AppShell';
import { PlanCard } from '@/features/billing/components/PlanCard';
import { PublicShell } from '@/features/marketing/components/PublicShell';
import { fetchPlans } from '@/lib/api/billing';
import { getCurrentUser } from '@/lib/auth/session';

// Rendered per request: the page shows the caller's own plan when they are signed in, and the
// build has no session to render that against.
export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'Pricing',
  description:
    'Take the diagnostic free. Upgrade when you know which categories are actually weak.',
};

interface PageProps {
  searchParams: Promise<{ checkout?: string }>;
}

/**
 * The pricing page.
 *
 * Public, and deliberately reachable without an account: a student deciding whether to start the
 * diagnostic is entitled to know what it leads to.
 *
 * The paywall argument is not made here — it is made on the results page, once a student has seen
 * which categories are weak. By the time anyone reads this page they already know what they would
 * be buying, so the page's job is to be clear rather than persuasive.
 *
 * Chrome depends on who is asking: the public navbar and footer for a visitor, the app shell for
 * a signed-in student. Rendering neither left the page a dead end with no way back.
 */
export default async function PricingPage({ searchParams }: PageProps) {
  const { checkout } = await searchParams;
  const [{ plans, entitlement, billing_enabled }, user] = await Promise.all([
    fetchPlans(),
    getCurrentUser(),
  ]);

  const content = (
    <main className="mx-auto w-full max-w-5xl px-6 py-16">
      <div className="max-w-2xl">
        <p className="label-micro">Pricing</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-tight text-text-primary">
          You found the gaps. Now close them.
        </h1>
        <p className="mt-4 text-base leading-relaxed text-text-secondary">
          The diagnostic is free and always will be — it is how you find out where you stand. Paid
          access is for the part that comes after: adaptive practice that keeps returning to what
          you got wrong, until you stop getting it wrong.
        </p>
      </div>

      {checkout === 'cancelled' ? (
        <div className="mt-8 rounded-md border border-border-subtle bg-surface-2 px-4 py-3 text-sm text-text-secondary">
          Checkout was cancelled. Nothing was charged, and your account is unchanged.
        </div>
      ) : null}

      {entitlement?.expired_at && !entitlement.is_paid ? (
        <div className="mt-8 rounded-md border border-band-developing/40 bg-band-developing/10 px-4 py-3 text-sm text-band-developing">
          Your access ended on{' '}
          {new Date(entitlement.expired_at).toLocaleDateString(undefined, {
            day: 'numeric',
            month: 'long',
            year: 'numeric',
          })}
          . Your history and mastery are all still here — renew below to keep practising.
        </div>
      ) : null}

      <div className="mt-10 grid gap-5 md:grid-cols-3">
        {plans.map((plan) => (
          <PlanCard
            key={plan.plan}
            plan={plan}
            entitlement={entitlement}
            billingEnabled={billing_enabled}
            emphasised={plan.plan === 'season_pass'}
          />
        ))}
      </div>

      <div className="mt-10 border-t border-border-subtle pt-8">
        <h2 className="text-sm font-medium text-text-primary">What the free tier includes</h2>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-secondary">
          The full 24-question diagnostic, graded by the same path paid practice uses — not a
          sample, not a preview. You get your category mastery, your weakest area, and your
          recommended next step. Practice sets and daily grading are limited; everything you have
          already answered stays readable for as long as you have an account.
        </p>

        <p className="mt-6 text-sm text-text-secondary">
          Not measured yet?{' '}
          <Link href="/diagnostic" className="text-accent hover:underline">
            Take the free diagnostic
          </Link>{' '}
          first — buying practice before you know what is weak is buying the wrong thing.
        </p>
      </div>
    </main>
  );

  return user ? (
    <AppShell email={user.email} isAdmin={user.is_admin} current="/pricing">
      {content}
    </AppShell>
  ) : (
    <PublicShell>{content}</PublicShell>
  );
}
