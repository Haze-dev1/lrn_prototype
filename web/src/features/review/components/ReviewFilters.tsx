'use client';

import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import type { Route } from 'next';
import { useTransition, type ReactNode } from 'react';

import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/Select';
import type { Category } from '@/lib/api/questions';

export interface ReviewFiltersProps {
  categories: Category[];
}

/**
 * An on/off filter chip.
 *
 * Local to this file rather than promoted to `components/ui`: one surface uses this shape, and a
 * shared component built for a single caller is a guess about the second one.
 */
function FilterToggle({
  active,
  disabled,
  onClick,
  children,
}: {
  active: boolean;
  disabled: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={active}
      className={[
        'inline-flex h-10 items-center rounded-md border px-3 text-sm transition-colors',
        'disabled:cursor-not-allowed disabled:opacity-60',
        active
          ? 'border-accent bg-accent-muted/30 text-text-primary'
          : 'border-border-subtle text-text-secondary hover:border-border-strong hover:text-text-primary',
      ].join(' ')}
    >
      {children}
    </button>
  );
}

/**
 * Filters for review history.
 *
 * State lives in the URL, so a filtered view is linkable and survives a refresh, and the server
 * component does the fetching. The filters offered are the ones that make an answer worth
 * reopening — a category, a low score, a dispute, recency — rather than every field the API
 * could sort on.
 */
export function ReviewFilters({ categories }: ReviewFiltersProps) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [pending, startTransition] = useTransition();

  function apply(next: URLSearchParams) {
    // Any filter change invalidates the cursor, which points into the previous result set.
    next.delete('before');
    const query = next.toString();
    startTransition(() => router.push((query ? `${pathname}?${query}` : pathname) as Route));
  }

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    apply(next);
  }

  function toggle(key: string) {
    const next = new URLSearchParams(params.toString());
    if (next.has(key)) next.delete(key);
    else next.set(key, 'true');
    apply(next);
  }

  const hasFilters = ['category_slug', 'max_score', 'flagged_only', 'recent_only', 'missed_concept'].some(
    (key) => params.has(key),
  );

  return (
    <div
      aria-busy={pending}
      className={['flex flex-wrap items-center gap-3 transition-opacity', pending ? 'opacity-60' : ''].join(' ')}
    >
      <div className="w-56">
        <label htmlFor="review-category" className="sr-only">
          Category
        </label>
        <Select
          id="review-category"
          value={params.get('category_slug') ?? ''}
          onChange={(event) => setParam('category_slug', event.target.value)}
          disabled={pending}
        >
          <option value="">All categories</option>
          {categories.map((category) => (
            <option key={category.slug} value={category.slug}>
              {category.name}
            </option>
          ))}
        </Select>
      </div>

      <div className="w-44">
        <label htmlFor="review-score" className="sr-only">
          Score
        </label>
        <Select
          id="review-score"
          value={params.get('max_score') ?? ''}
          onChange={(event) => setParam('max_score', event.target.value)}
          disabled={pending}
        >
          <option value="">Any score</option>
          <option value="54">Needs work (≤ 54)</option>
          <option value="74">Below strong (≤ 74)</option>
        </Select>
      </div>

      {/* Bordered in both states. A ghost button sitting beside two bordered selects reads as a
          caption rather than a control, and a filter nobody recognises as a filter is a filter
          nobody uses. The active state fills rather than merely outlines, so which filters are on
          is legible at a glance. */}
      <FilterToggle
        active={params.has('recent_only')}
        disabled={pending}
        onClick={() => toggle('recent_only')}
      >
        Last two weeks
      </FilterToggle>

      <FilterToggle
        active={params.has('flagged_only')}
        disabled={pending}
        onClick={() => toggle('flagged_only')}
      >
        Flagged
      </FilterToggle>

      {hasFilters ? (
        <Button variant="ghost" onClick={() => apply(new URLSearchParams())} disabled={pending}>
          Clear
        </Button>
      ) : null}
    </div>
  );
}
