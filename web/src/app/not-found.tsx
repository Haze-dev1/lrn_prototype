import type { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = { title: 'Not found' };

/**
 * The 404.
 *
 * Next's default is an unstyled black page with a status code and no way off it, which is a dead
 * end in a product whose stated rule is that there are none. This one is in the product's voice,
 * says the two things that are actually true — the page is gone, the student's work is not — and
 * offers the routes someone at a broken link most likely wants.
 *
 * It stands alone rather than inside the application shell: this page renders for signed-out
 * visitors too, and the shell needs a session it may not have.
 */
export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-xl flex-col justify-center px-6 py-16">
      <p className="label-micro">404</p>
      <h1 className="mt-3 text-3xl font-semibold tracking-tight text-text-primary">
        This page is not here.
      </h1>
      <p className="mt-4 leading-relaxed text-text-secondary">
        The link may be old, or the session it points at may belong to a different account.
        Nothing you have answered is affected — your history, mastery and review are all intact.
      </p>

      <nav aria-label="Recovery" className="mt-8 flex flex-wrap items-center gap-3">
        <Link
          href="/dashboard"
          className="inline-flex h-10 items-center justify-center rounded-md bg-text-primary px-4 text-sm font-medium text-text-inverse transition-colors hover:bg-white"
        >
          Go to your dashboard
        </Link>
        <Link
          href="/review"
          className="inline-flex h-10 items-center justify-center rounded-md border border-border-subtle px-4 text-sm text-text-secondary transition-colors hover:border-border-strong hover:text-text-primary"
        >
          Review your answers
        </Link>
      </nav>
    </main>
  );
}
