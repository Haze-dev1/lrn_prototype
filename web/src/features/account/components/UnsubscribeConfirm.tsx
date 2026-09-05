'use client';

import Link from 'next/link';
import { useState } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { unsubscribeWithToken } from '@/lib/api/auth';

/**
 * The page an emailed unsubscribe link opens.
 *
 * It asks for one click rather than acting on page load, and that is the whole design. Mail
 * scanners, link previewers and corporate security proxies fetch every URL in a message the
 * moment it arrives — a page that unsubscribed on render would silently unsubscribe people who
 * never opened the email.
 *
 * No sign-in, by design. Someone who wants the mail to stop must be able to stop it here; the
 * only other control they have is the spam button, and using it costs the whole domain.
 */
export function UnsubscribeConfirm({ token }: { token: string }) {
  const [state, setState] = useState<'idle' | 'working' | 'done' | 'error'>('idle');

  async function handleClick() {
    setState('working');
    try {
      await unsubscribeWithToken(token);
      setState('done');
    } catch {
      setState('error');
    }
  }

  if (state === 'done') {
    return (
      <div className="space-y-5">
        <div>
          <p className="label-micro text-band-strong">Unsubscribed</p>
          <h1 className="mt-3 text-2xl font-semibold tracking-tight text-text-primary">
            Study reminders are off.
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-text-secondary">
            You will still get your diagnostic results and payment confirmations — those are
            replies to things you did, not a mailing list. Nothing else changes: your history,
            mastery and review are all still here.
          </p>
        </div>
        <Link
          href="/account"
          className="inline-flex h-10 items-center justify-center rounded-md border border-border-subtle px-4 text-sm text-text-secondary transition-colors hover:border-border-strong hover:text-text-primary"
        >
          Manage all email preferences
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <p className="label-micro">Email preferences</p>
        <h1 className="mt-3 text-2xl font-semibold tracking-tight text-text-primary">
          Turn off study reminders?
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-text-secondary">
          You will stop receiving the weekly email about your weakest area. Your diagnostic
          results and payment confirmations will still arrive, and your account is untouched.
        </p>
      </div>

      {state === 'error' ? (
        <Alert tone="error">
          We could not update your preference. Please try again, or turn reminders off from your
          account page.
        </Alert>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <Button loading={state === 'working'} onClick={handleClick}>
          Turn off study reminders
        </Button>
        <Link
          href="/dashboard"
          className="inline-flex h-10 items-center justify-center px-2 text-sm text-text-secondary transition-colors hover:text-text-primary"
        >
          Keep them on
        </Link>
      </div>
    </div>
  );
}
