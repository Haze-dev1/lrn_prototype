'use client';

import { useState } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { Select } from '@/components/ui/Select';
import { Textarea } from '@/components/ui/Textarea';
import { ApiError } from '@/lib/api/client';
import { FLAG_REASONS, flagGrade, type FlagReason } from '@/lib/api/review';

export interface FlagGradeControlProps {
  attemptId: string;
  alreadyFlagged: boolean;
}

/**
 * Disputing a grade.
 *
 * Deliberately understated — a small text link rather than a button competing with the coaching.
 * It has to be present, because a student who believes a grade is wrong and has no way to say so
 * stops trusting every other grade. It should not be prominent, because inviting a dispute after
 * every low score would turn the product into an argument.
 *
 * Once raised it collapses to a plain acknowledgement. A flag is a statement, not a vote, and
 * re-offering the control would suggest repeating it does something.
 */
export function FlagGradeControl({ attemptId, alreadyFlagged }: FlagGradeControlProps) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<FlagReason>('score_too_low');
  const [comment, setComment] = useState('');
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(alreadyFlagged);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    setError(null);
    setSending(true);
    try {
      await flagGrade(attemptId, { reason, comment: comment.trim() || null });
      setSent(true);
      setOpen(false);
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : 'Could not send that. Please try again.',
      );
    } finally {
      setSending(false);
    }
  }

  if (sent) {
    return (
      <p className="text-xs text-text-muted">
        You flagged this grade. Flags are reviewed and used to improve the question, not just to
        answer you.
      </p>
    );
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-xs text-text-muted underline-offset-4 hover:text-text-secondary hover:underline"
      >
        Flag this grade
      </button>
    );
  }

  return (
    <div className="space-y-4 rounded-[--radius-card] border border-border-subtle bg-surface-1 p-5">
      <p className="label-micro">Flag this grade</p>
      {error ? <Alert tone="error">{error}</Alert> : null}

      <Field id="flag-reason" label="What is wrong with it?">
        <Select
          id="flag-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value as FlagReason)}
          disabled={sending}
        >
          {FLAG_REASONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
      </Field>

      <Field id="flag-comment" label="Anything to add?" hint="Optional.">
        <Textarea
          id="flag-comment"
          rows={3}
          maxLength={1000}
          value={comment}
          onChange={(event) => setComment(event.target.value)}
          disabled={sending}
        />
      </Field>

      <div className="flex gap-3">
        <Button size="sm" loading={sending} onClick={handleSubmit}>
          Send
        </Button>
        <Button size="sm" variant="ghost" disabled={sending} onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
