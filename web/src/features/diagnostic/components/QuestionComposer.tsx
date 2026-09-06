'use client';

import { useEffect, useRef, useState } from 'react';
import { Textarea } from '@/components/ui/Textarea';
import { cn } from '@/utils/cn';
import { PenLine } from 'lucide-react';

const MAX_ANSWER_LENGTH = 2000;
const MIN_USEFUL_LENGTH = 20;

export interface QuestionComposerProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

export function QuestionComposer({ value, onChange, disabled = false }: QuestionComposerProps) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [touched, setTouched] = useState(false);
  const [focused, setFocused] = useState(false);

  useEffect(() => {
    ref.current?.focus();
  }, []);

  const remaining = MAX_ANSWER_LENGTH - value.length;
  const tooShort = touched && value.trim().length > 0 && value.trim().length < MIN_USEFUL_LENGTH;

  return (
    <div className={cn(
      "relative rounded-[--radius-lg] border bg-surface-1 transition-all duration-300",
      focused ? "border-accent shadow-[0_0_0_1px_var(--color-accent)]" : "border-border-strong hover:border-border-subtle"
    )}>
      <label htmlFor="answer" className="sr-only">
        Your answer
      </label>
      
      {/* Workspace Header */}
      <div className="flex items-center gap-2 border-b border-border-subtle bg-surface-2/50 px-4 py-2.5 rounded-t-[--radius-lg]">
        <PenLine className="w-4 h-4 text-text-muted" />
        <span className="label-micro">Draft Answer</span>
      </div>

      <Textarea
        id="answer"
        ref={ref}
        rows={10}
        value={value}
        maxLength={MAX_ANSWER_LENGTH}
        disabled={disabled}
        placeholder="Structure your answer carefully, as you would in a technical interview."
        className="w-full resize-y border-none bg-transparent px-4 py-4 text-base leading-relaxed text-text-primary placeholder:text-text-muted focus:ring-0 focus-visible:ring-0 rounded-b-[--radius-lg] min-h-[200px]"
        onChange={(event) => onChange(event.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => {
          setFocused(false);
          setTouched(true);
        }}
        aria-describedby="answer-meta"
        style={{ boxShadow: 'none' }}
      />
      
      {/* Footer Info */}
      <div id="answer-meta" className="flex justify-between items-center px-4 py-3 border-t border-border-subtle bg-surface-1/50 rounded-b-[--radius-lg]">
        <span className={cn("text-xs font-medium", tooShort ? 'text-band-developing' : 'text-text-muted')}>
          {tooShort ? 'Write a bit more to submit.' : 'Clear and structured is better than long.'}
        </span>
        <div className="flex items-center gap-4">
          <div className="w-24 h-1 rounded-full bg-surface-3 overflow-hidden hidden sm:block">
            <div 
              className="h-full bg-accent transition-all duration-300"
              style={{ width: `${Math.min(100, (value.length / MIN_USEFUL_LENGTH) * 100)}%` }}
            />
          </div>
          <span className={cn("tabular text-xs font-mono font-medium", remaining < 100 ? 'text-band-developing' : 'text-text-muted')}>
            {remaining} left
          </span>
        </div>
      </div>
    </div>
  );
}

export { MIN_USEFUL_LENGTH };
