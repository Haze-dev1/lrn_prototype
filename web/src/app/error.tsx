'use client';

import Link from 'next/link';
import { useEffect } from 'react';

import { Button } from '@/components/ui/Button';

/**
 * The route error boundary.
 *
 * Without it, an unhandled failure in a Server Component renders Next's own error screen — which
 * in production reads "Application error: a server-side exception has occurred" and offers
 * nothing to do about it. That is a raw internal failure shown to a student, which the product's
 * standards rule out.
 *
 * The error's message is deliberately never rendered. It can carry a query, a path, or an
 * upstream provider's wording, and none of that belongs on a student's screen. The digest is
 * shown instead: it is a hash Next also writes to the server log, so a student can quote it and
 * someone can find the actual error without it ever being displayed.
 */
export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // The browser console is the only place the detail belongs, and only in development — the
    // production build strips nothing, so this stays a console call rather than a rendered node.
    console.error('Route error', error);
  }, [error]);

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-xl flex-col justify-center px-6 py-16">
      <p className="label-micro text-band-needs-work">Something went wrong</p>
      <h1 className="mt-3 text-3xl font-semibold tracking-tight text-text-primary">
        This page could not be loaded.
      </h1>
      <p className="mt-4 leading-relaxed text-text-secondary">
        The failure was on our side, and nothing you have answered is affected. Try again — if it
        keeps happening, your dashboard is still reachable.
      </p>

      <div className="mt-8 flex flex-wrap items-center gap-3">
        <Button onClick={reset}>Try again</Button>
        <Link
          href="/dashboard"
          className="inline-flex h-10 items-center justify-center rounded-md border border-border-subtle px-4 text-sm text-text-secondary transition-colors hover:border-border-strong hover:text-text-primary"
        >
          Go to your dashboard
        </Link>
      </div>

      {error.digest ? (
        <p className="mt-8 font-mono text-xs text-text-muted">
          Reference {error.digest}
        </p>
      ) : null}
    </main>
  );
}
