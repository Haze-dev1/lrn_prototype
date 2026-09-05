'use client';

import { useEffect, useState } from 'react';

import { Alert } from '@/components/ui/Alert';
import { fetchResults, type SessionResults } from '@/lib/api/sessions';

const POLL_INTERVAL_MS = 2000;
// Roughly two minutes. Past this the retry sweep owns the problem, and a spinner that never
// resolves is worse than an honest "come back shortly".
const MAX_POLLS = 60;

export interface GradingProgressPanelProps {
  sessionId: string;
  initial: SessionResults;
}

/**
 * Grading progress, while grading is still running.
 *
 * There is no fake "AI is thinking" animation and no simulated typing. What is shown is the real
 * count of answers graded so far, because it is true and because a student who has just committed
 * 24 answers is owed an honest signal rather than a performance.
 *
 * When everything resolves the page reloads through the router so the server component renders
 * the real results — the same code path as arriving at a finished diagnostic directly, rather
 * than a second client-side rendering of the same thing.
 */
export function GradingProgressPanel({ sessionId, initial }: GradingProgressPanelProps) {
  const [progress, setProgress] = useState(initial.progress);
  const [stalled, setStalled] = useState(false);

  useEffect(() => {
    if (progress.grading_complete) return;

    let polls = 0;
    let cancelled = false;

    const timer = setInterval(async () => {
      polls += 1;
      if (polls > MAX_POLLS) {
        clearInterval(timer);
        if (!cancelled) setStalled(true);
        return;
      }
      try {
        const next = await fetchResults(sessionId);
        if (cancelled) return;
        setProgress(next.progress);
        if (next.progress.grading_complete) {
          clearInterval(timer);
          // Full reload rather than router.refresh(): the results are rendered by a Server
          // Component, and this is the simplest way to hand rendering back to it.
          window.location.reload();
        }
      } catch {
        // A single failed poll is not worth surfacing; the next one will either succeed or the
        // poll budget will run out and say so.
      }
    }, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [sessionId, progress.grading_complete]);

  const done = progress.graded + progress.failed;
  const percent = progress.answered === 0 ? 0 : Math.round((done / progress.answered) * 100);

  return (
    <section
      aria-labelledby="grading-heading"
      aria-live="polite"
      className="rounded-[--radius-card] border border-border-subtle bg-surface-1 p-8 text-center"
    >
      <h2 id="grading-heading" className="label-micro">
        Grading
      </h2>
      <p className="mt-4 text-2xl font-medium text-text-primary">
        <span className="tabular">{done}</span> of{' '}
        <span className="tabular">{progress.answered}</span> answers graded
      </p>
      <p className="mt-2 text-sm text-text-secondary">
        Each answer is read against the same rubric an interviewer would use. This usually takes
        under a minute.
      </p>

      <div className="mx-auto mt-6 h-1.5 max-w-sm overflow-hidden rounded-full bg-surface-3">
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-500 ease-out"
          style={{ width: `${Math.max(percent, 3)}%` }}
        />
      </div>

      {stalled ? (
        <div className="mt-6 text-left">
          <Alert tone="info">
            Grading is taking longer than usual. Your answers are saved and grading will finish on
            its own — reload this page in a few minutes.
          </Alert>
        </div>
      ) : null}
    </section>
  );
}
