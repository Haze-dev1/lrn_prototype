'use client';

import { useEffect, useRef, useState } from 'react';

import { Textarea } from '@/components/ui/Textarea';

const MAX_ANSWER_LENGTH = 2000;
// Below this the answer is almost certainly not a real attempt, so the submit action stays
// disabled rather than spending a grading call to tell the student their two words were thin.
const MIN_USEFUL_LENGTH = 20;

export interface QuestionComposerProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

/**
 * The answer input.
 *
 * Deliberately a plain, large textarea. This is the surface a student spends most of the
 * assessment looking at, and every affordance beyond "write your answer" — formatting controls,
 * suggestions, a chat transcript — would change what the product appears to be. It is a written
 * exam answer, not a conversation.
 */
export function QuestionComposer({ value, onChange, disabled = false }: QuestionComposerProps) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [touched, setTouched] = useState(false);

  // Focus on mount so a keyboard user can start typing without tabbing in. The parent keys this
  // component on the question ID, so moving to a new question remounts it — which resets the
  // draft and `touched` for free, rather than resetting them from inside an effect.
  useEffect(() => {
    ref.current?.focus();
  }, []);

  const remaining = MAX_ANSWER_LENGTH - value.length;
  const tooShort = touched && value.trim().length > 0 && value.trim().length < MIN_USEFUL_LENGTH;

  return (
    <div className="space-y-2">
      <label htmlFor="answer" className="sr-only">
        Your answer
      </label>
      <Textarea
        id="answer"
        ref={ref}
        rows={12}
        value={value}
        maxLength={MAX_ANSWER_LENGTH}
        disabled={disabled}
        placeholder="Answer as you would out loud in an interview."
        onChange={(event) => onChange(event.target.value)}
        onBlur={() => setTouched(true)}
        aria-describedby="answer-meta"
      />
      <div id="answer-meta" className="flex justify-between text-xs">
        <span className="text-text-muted">
          {tooShort ? 'Write a little more before submitting.' : 'Structure beats length.'}
        </span>
        <span className={remaining < 100 ? 'tabular text-band-developing' : 'tabular text-text-muted'}>
          {remaining} left
        </span>
      </div>
    </div>
  );
}

export { MIN_USEFUL_LENGTH };
