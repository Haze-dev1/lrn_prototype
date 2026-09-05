import type { Metadata } from 'next';

import { UnsubscribeConfirm } from '@/features/account/components/UnsubscribeConfirm';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = { title: 'Email preferences' };

interface PageProps {
  searchParams: Promise<{ token?: string }>;
}

/**
 * Where an emailed unsubscribe link lands.
 *
 * Public and outside the app shell: the reader is not signed in, and asking them to be would
 * defeat the point. The token in the query string is not trusted here — it is passed to the API,
 * which verifies its signature and can only ever use it to turn a preference off.
 */
export default async function UnsubscribePage({ searchParams }: PageProps) {
  const { token } = await searchParams;

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-xl flex-col justify-center px-6 py-16">
      {token ? (
        <UnsubscribeConfirm token={token} />
      ) : (
        <div>
          <p className="label-micro">Email preferences</p>
          <h1 className="mt-3 text-2xl font-semibold tracking-tight text-text-primary">
            This link is incomplete.
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-text-secondary">
            Open the link from your email again, or sign in and change your email preferences from
            your account page.
          </p>
        </div>
      )}
    </main>
  );
}
