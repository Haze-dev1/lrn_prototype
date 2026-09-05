import type { Metadata } from 'next';

import { AppShell } from '@/components/layout/AppShell';
import { ConsentControl } from '@/features/account/components/ConsentControl';
import { DataControls } from '@/features/account/components/DataControls';
import { EmailPreferences } from '@/features/account/components/EmailPreferences';
import { ProfileForm } from '@/features/account/components/ProfileForm';
import { BillingPanel } from '@/features/billing/components/BillingPanel';
import { fetchEmailPreferences } from '@/lib/api/auth';
import { fetchEntitlement } from '@/lib/api/billing';
import { requireUser } from '@/lib/auth/session';

// Rendered per request, never prerendered: the page depends on the caller's session, and the
// build has no session (and no reachable API) to render against.
export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'Account' };

export default async function AccountPage() {
  const user = await requireUser('/account');
  const [entitlement, emailPreferences] = await Promise.all([
    fetchEntitlement(),
    fetchEmailPreferences(),
  ]);

  return (
    <AppShell email={user.email} isAdmin={user.is_admin} current="/account">
      <main className="mx-auto w-full max-w-2xl space-y-6 px-6 py-12">
        <div>
          <p className="label-micro">Account</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight text-text-primary">
            Your account
          </h1>
        </div>

        <BillingPanel entitlement={entitlement} />
        <ProfileForm email={user.email} profile={user.profile} />
        <ConsentControl profile={user.profile} />
        <EmailPreferences initial={emailPreferences} />
        {/* Only shapes the form. The API independently decides whether a password is required,
            and refuses the deletion if one is needed and missing. */}
        <DataControls hasPassword />
      </main>
    </AppShell>
  );
}
