import type { Metadata } from 'next';

import { AppShell } from '@/components/layout/AppShell';
import { ConfirmingAccess } from '@/features/billing/components/ConfirmingAccess';
import { fetchEntitlement } from '@/lib/api/billing';
import { requireUser } from '@/lib/auth/session';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'Confirming your access' };

/**
 * Where the payment provider returns a student after a successful checkout.
 *
 * Reads entitlement on the server first so the common case — the webhook already landed while the
 * browser was redirecting — renders as confirmed immediately, with no spinner at all.
 */
export default async function BillingSuccessPage() {
  const user = await requireUser('/billing/success');
  const entitlement = await fetchEntitlement();

  return (
    <AppShell email={user.email} isAdmin={user.is_admin} current="/account">
      <main className="mx-auto w-full max-w-xl px-6 py-16">
        <ConfirmingAccess initial={entitlement} />
      </main>
    </AppShell>
  );
}
