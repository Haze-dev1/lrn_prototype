'use client';

import { useRouter } from 'next/navigation';
import type { Route } from 'next';
import { useState } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { AllowanceMeter } from '@/features/billing/components/AllowanceMeter';
import { PaywallNotice } from '@/features/billing/components/PaywallNotice';
import { paywallDetail, type Entitlement, type PaywallDetail } from '@/lib/api/billing';
import { ApiError } from '@/lib/api/client';
import type { Category } from '@/lib/api/questions';
import { PRACTICE_SET_SIZES, startPractice, type PracticeSetSize } from '@/lib/api/sessions';

const MINUTES_PER_QUESTION = 3;

export interface StartPracticeFormProps {
  categories: Category[];
  /** Pre-selected from a "practise this" link. */
  initialCategory?: string | null;
  /** The caller's server-decided access. Hides the control; the API still enforces the limit. */
  entitlement: Entitlement;
}

/**
 * Choosing a practice set.
 *
 * Three lengths and an optional category, and nothing else. The engine decides which questions to
 * ask; offering a student difficulty sliders or topic checkboxes would let them avoid exactly the
 * material the selection exists to put in front of them.
 *
 * "Let the engine choose" is the default, and it is listed first, because it is the right answer
 * for almost every student almost every time.
 */
export function StartPracticeForm({
  categories,
  initialCategory,
  entitlement,
}: StartPracticeFormProps) {
  const router = useRouter();
  const [size, setSize] = useState<PracticeSetSize>(10);
  const [category, setCategory] = useState(initialCategory ?? '');
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Seeded from the server's decision so an exhausted allowance is a paywall on first paint, not
  // after a click that was always going to be refused.
  const [paywall, setPaywall] = useState<PaywallDetail | null>(null);

  const blocked = !entitlement.can_start_practice;

  async function handleStart() {
    setError(null);
    setPaywall(null);
    setStarting(true);
    try {
      const session = await startPractice({
        size,
        category_slug: category === '' ? null : category,
      });
      router.push(`/practice/${session.id}` as Route);
    } catch (caught) {
      // A 402 is not a failure to report — it is a boundary to explain, and it carries the
      // numbers to explain it with.
      const limit = paywallDetail(caught);
      if (limit) {
        setPaywall(limit);
      } else {
        setError(
          caught instanceof ApiError ? caught.message : 'Could not start. Please try again.',
        );
      }
      setStarting(false);
    }
  }

  return (
    <div className="space-y-8">
      {error ? <Alert tone="error">{error}</Alert> : null}
      {paywall ? <PaywallNotice detail={paywall} /> : null}
      {blocked && !paywall ? (
        <PaywallNotice
          detail={{
            reason: 'practice_limit_reached',
            message: `You have used all ${entitlement.usage.practice_sessions_limit} free practice sets. Upgrade for unlimited adaptive practice.`,
            used: entitlement.usage.practice_sessions_used,
            limit: entitlement.usage.practice_sessions_limit,
            upgrade_url: '/pricing',
          }}
        />
      ) : null}

      <fieldset disabled={starting || blocked}>
        <legend className="label-micro">How many questions</legend>
        <div className="mt-3 grid grid-cols-3 gap-3">
          {PRACTICE_SET_SIZES.map((option) => {
            const selected = option === size;
            return (
              <button
                key={option}
                type="button"
                aria-pressed={selected}
                onClick={() => setSize(option)}
                className={[
                  'rounded-[--radius-card] border px-4 py-5 text-left transition-colors',
                  selected
                    ? 'border-accent bg-surface-2'
                    : 'border-border-subtle bg-surface-1 hover:border-border-strong',
                ].join(' ')}
              >
                <span className="tabular block text-2xl font-semibold text-text-primary">
                  {option}
                </span>
                <span className="mt-1 block text-xs text-text-muted">
                  ~{option * MINUTES_PER_QUESTION} min
                </span>
              </button>
            );
          })}
        </div>
      </fieldset>

      <fieldset disabled={starting || blocked}>
        <legend className="label-micro">What to practise</legend>
        <div className="mt-3 space-y-2">
          <label
            className={[
              'flex cursor-pointer items-center gap-3 rounded-md border px-4 py-3 text-sm transition-colors',
              category === ''
                ? 'border-accent bg-surface-2 text-text-primary'
                : 'border-border-subtle text-text-secondary hover:border-border-strong',
            ].join(' ')}
          >
            <input
              type="radio"
              name="category"
              value=""
              checked={category === ''}
              onChange={() => setCategory('')}
              className="accent-accent"
            />
            Let the engine choose — targets your weakest areas and anything due for review
          </label>

          <div className="grid gap-2 sm:grid-cols-2">
            {categories.map((option) => (
              <label
                key={option.slug}
                className={[
                  'flex cursor-pointer items-center gap-3 rounded-md border px-4 py-3 text-sm transition-colors',
                  category === option.slug
                    ? 'border-accent bg-surface-2 text-text-primary'
                    : 'border-border-subtle text-text-secondary hover:border-border-strong',
                ].join(' ')}
              >
                <input
                  type="radio"
                  name="category"
                  value={option.slug}
                  checked={category === option.slug}
                  onChange={() => setCategory(option.slug)}
                  className="accent-accent"
                />
                {option.name}
              </label>
            ))}
          </div>
        </div>
      </fieldset>

      <div className="space-y-3">
        <Button size="lg" loading={starting} disabled={blocked} onClick={handleStart}>
          Start practising
        </Button>
        <AllowanceMeter entitlement={entitlement} kind="practice" />
      </div>
    </div>
  );
}
