'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { ApiError } from '@/lib/api/client';
import { setQuestionStatus, type QuestionStatus } from '@/lib/api/admin';

const STATUS_TONE: Record<QuestionStatus, BadgeTone> = {
  active: 'strong',
  draft: 'developing',
  retired: 'neutral',
};

export interface LifecycleControlProps {
  questionId: string;
  status: QuestionStatus;
  hasPublishedVersion: boolean;
}

/**
 * Activate or retire a question.
 *
 * Activation is disabled without a published version and says why, mirroring the API's own guard.
 * The button is hidden from a client that cannot use it, but the server still refuses the call —
 * this control shapes the interface, it does not enforce the rule.
 */
export function LifecycleControl({
  questionId,
  status,
  hasPublishedVersion,
}: LifecycleControlProps) {
  const router = useRouter();
  const [pending, setPending] = useState<QuestionStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function change(next: QuestionStatus) {
    setError(null);
    setPending(next);
    try {
      await setQuestionStatus(questionId, next);
      router.refresh();
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : 'Something went wrong. Please try again.',
      );
    } finally {
      setPending(null);
    }
  }

  return (
    <section
      aria-labelledby="lifecycle-heading"
      className="rounded-[--radius-card] border border-border-subtle bg-surface-1 p-5"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 id="lifecycle-heading" className="label-micro">
          Status
        </h2>
        <Badge tone={STATUS_TONE[status]}>{status}</Badge>
      </div>

      {error ? (
        <div className="mt-3">
          <Alert tone="error">{error}</Alert>
        </div>
      ) : null}

      <p className="mt-3 text-sm text-text-secondary">
        {status === 'active'
          ? 'This question is in the live pool and can be selected into sessions.'
          : status === 'retired'
            ? 'Retired. It is no longer selected, and past attempts keep their grades.'
            : 'A draft is never shown to students.'}
      </p>

      <div className="mt-4 flex flex-wrap gap-2">
        {status !== 'active' ? (
          <Button
            size="sm"
            loading={pending === 'active'}
            disabled={pending !== null || !hasPublishedVersion}
            onClick={() => change('active')}
          >
            Activate
          </Button>
        ) : null}
        {status !== 'retired' ? (
          <Button
            size="sm"
            variant="secondary"
            loading={pending === 'retired'}
            disabled={pending !== null}
            onClick={() => change('retired')}
          >
            Retire
          </Button>
        ) : null}
        {status === 'retired' ? (
          <Button
            size="sm"
            variant="secondary"
            loading={pending === 'draft'}
            disabled={pending !== null}
            onClick={() => change('draft')}
          >
            Return to draft
          </Button>
        ) : null}
      </div>

      {!hasPublishedVersion && status !== 'active' ? (
        <p className="mt-3 text-xs text-text-muted">
          Publish a version before activating. An active question with no rubric cannot be graded.
        </p>
      ) : null}
    </section>
  );
}
