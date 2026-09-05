'use client';

import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/Button';
import { fetchEntitlement, type Entitlement } from '@/lib/api/billing';

const POLL_INTERVAL_MS = 2_000;
// Roughly a minute. Stripe usually delivers in seconds; past this the honest thing is to stop
// spinning and tell the student their payment is safe and access is coming, rather than imply
// something is broken by polling forever.
const MAX_POLLS = 30;

/**
 * The page a student lands on after paying.
 *
 * It confirms access; it never grants it. The browser has just come back from the payment
 * provider and knows the payment succeeded, and that knowledge is worth nothing here — the
 * entitlement appears when the signed webhook lands, so this polls the API until the server
 * agrees. Trusting the redirect would mean anyone who can type this URL has bought a plan.
 *
 * Real timers rather than fake ones, and a plain interval rather than a subscription: the state
 * being waited on is a single boolean, and it either flips or it does not.
 */
export function ConfirmingAccess({ initial }: { initial: Entitlement }) {
  const router = useRouter();
  const [entitlement, setEntitlement] = useState(initial);
  const [attempts, setAttempts] = useState(0);

  const confirmed = entitlement.is_paid;
  const timedOut = !confirmed && attempts >= MAX_POLLS;

  useEffect(() => {
    if (confirmed || timedOut) return;

    const timer = setTimeout(async () => {
      try {
        setEntitlement(await fetchEntitlement());
      } catch {
        // A failed poll is not a failed payment. The next tick tries again, and the timeout
        // below is what eventually stops it.
      } finally {
        setAttempts((count) => count + 1);
      }
    }, POLL_INTERVAL_MS);

    return () => clearTimeout(timer);
  }, [attempts, confirmed, timedOut]);

  if (confirmed) {
    return (
      <div className="space-y-6">
        <div>
          <p className="label-micro text-band-strong">Payment confirmed</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight text-text-primary">
            You have full access.
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-text-secondary">
            Adaptive practice, spaced repetition of everything you have missed, and your full
            review history are all open. The best next move is the one your results already
            pointed at.
          </p>
        </div>

        <div className="flex flex-wrap gap-3">
          <Button size="lg" onClick={() => router.push('/practice')}>
            Start practising
          </Button>
          <Link
            href="/dashboard"
            className="inline-flex h-12 items-center justify-center rounded-md border border-border-subtle px-6 text-sm text-text-secondary transition-colors hover:border-border-strong hover:text-text-primary"
          >
            Back to dashboard
          </Link>
        </div>
      </div>
    );
  }

  if (timedOut) {
    return (
      <div className="space-y-5">
        <div>
          <p className="label-micro">Payment received</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight text-text-primary">
            We are still confirming your access.
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-text-secondary">
            Your payment went through and nothing is lost. Confirmation from our payment provider
            is taking longer than usual — access opens automatically as soon as it arrives, and it
            is normally within a minute or two.
          </p>
        </div>

        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" onClick={() => router.refresh()}>
            Check again
          </Button>
          <Link
            href="/dashboard"
            className="inline-flex h-10 items-center justify-center rounded-md px-4 text-sm text-text-secondary hover:text-text-primary"
          >
            Back to dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <p className="label-micro">Payment received</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-text-primary">
          Confirming your access.
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-text-secondary">
          Your payment went through. We are waiting for confirmation from our payment provider —
          this usually takes a few seconds.
        </p>
      </div>

      <div
        role="status"
        aria-live="polite"
        className="flex items-center gap-3 text-sm text-text-muted"
      >
        <span
          aria-hidden="true"
          className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent"
        />
        Waiting for confirmation…
      </div>
    </div>
  );
}
