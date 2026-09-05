import Link from 'next/link';

export interface SessionExitProps {
  /** Shapes the copy: a diagnostic resumes where it left off, a practice set does not. */
  kind: 'diagnostic' | 'practice';
}

/**
 * The way out of a session.
 *
 * The runners deliberately render without the application shell — a sidebar full of destinations
 * is an invitation to leave the one surface where a student should be looking at nothing but the
 * question. But "no exit" and "no distractions" are different things, and without this the only
 * way out of a 24-question sitting is the browser's back button.
 *
 * So: one link, muted, top-left, out of the way of the question. The copy carries the reassurance
 * that matters — a diagnostic resumes exactly where it was left, which is the fact that makes
 * leaving safe rather than costly.
 */
export function SessionExit({ kind }: SessionExitProps) {
  const label = kind === 'diagnostic' ? 'Save and exit' : 'Leave this set';
  const note =
    kind === 'diagnostic'
      ? 'Your answers are saved. You will come back to this question.'
      : 'Your answers are saved.';

  return (
    <div className="mx-auto mb-8 flex w-full max-w-3xl items-baseline justify-between gap-4">
      <span className="label-micro">LRN</span>
      <Link
        href="/dashboard"
        title={note}
        className="text-xs text-text-muted underline-offset-4 transition-colors hover:text-text-secondary hover:underline"
      >
        {label}
      </Link>
    </div>
  );
}
