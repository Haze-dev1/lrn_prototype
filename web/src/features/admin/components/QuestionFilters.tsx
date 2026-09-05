'use client';

import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import type { Route } from 'next';
import { useTransition, type FormEvent } from 'react';

import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import type { Category } from '@/lib/api/questions';

export interface QuestionFiltersProps {
  categories: Category[];
}

const STATUSES = [
  { value: 'draft', label: 'Draft' },
  { value: 'active', label: 'Active' },
  { value: 'retired', label: 'Retired' },
] as const;

/**
 * Filter controls for the question list.
 *
 * State lives in the URL rather than in component state, so a filtered view is linkable, survives
 * a refresh, and lets the server component do the fetching. Navigation is wrapped in a transition
 * so the current results stay on screen and dim rather than being replaced by a spinner.
 */
export function QuestionFilters({ categories }: QuestionFiltersProps) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [pending, startTransition] = useTransition();

  function apply(next: URLSearchParams) {
    // Any filter change invalidates the keyset cursor, which points into the previous result set.
    next.delete('before');
    const query = next.toString();
    startTransition(() => {
      router.push((query ? `${pathname}?${query}` : pathname) as Route);
    });
  }

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(params.toString());
    if (value) {
      next.set(key, value);
    } else {
      next.delete(key);
    }
    apply(next);
  }

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = new FormData(event.currentTarget).get('search');
    setParam('search', typeof value === 'string' ? value.trim() : '');
  }

  const hasFilters = ['category_slug', 'status', 'difficulty', 'search'].some((key) =>
    params.has(key),
  );

  return (
    <div
      aria-busy={pending}
      className={[
        'flex flex-wrap items-end gap-3 transition-opacity',
        pending ? 'opacity-60' : '',
      ].join(' ')}
    >
      <form onSubmit={handleSearch} className="flex min-w-56 flex-1 items-center gap-2">
        <label htmlFor="filter-search" className="sr-only">
          Search questions
        </label>
        <Input
          id="filter-search"
          name="search"
          type="search"
          placeholder="Search prompt, subcategory, or key"
          defaultValue={params.get('search') ?? ''}
          disabled={pending}
        />
        <Button type="submit" variant="secondary" size="md" disabled={pending}>
          Search
        </Button>
      </form>

      <div className="w-48">
        <label htmlFor="filter-category" className="sr-only">
          Category
        </label>
        <Select
          id="filter-category"
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

      <div className="w-36">
        <label htmlFor="filter-status" className="sr-only">
          Status
        </label>
        <Select
          id="filter-status"
          value={params.get('status') ?? ''}
          onChange={(event) => setParam('status', event.target.value)}
          disabled={pending}
        >
          <option value="">Any status</option>
          {STATUSES.map((status) => (
            <option key={status.value} value={status.value}>
              {status.label}
            </option>
          ))}
        </Select>
      </div>

      <div className="w-32">
        <label htmlFor="filter-difficulty" className="sr-only">
          Difficulty
        </label>
        <Select
          id="filter-difficulty"
          value={params.get('difficulty') ?? ''}
          onChange={(event) => setParam('difficulty', event.target.value)}
          disabled={pending}
        >
          <option value="">Any level</option>
          {[1, 2, 3, 4, 5].map((level) => (
            <option key={level} value={level}>
              Level {level}
            </option>
          ))}
        </Select>
      </div>

      {hasFilters ? (
        <Button
          type="button"
          variant="ghost"
          onClick={() => apply(new URLSearchParams())}
          disabled={pending}
        >
          Clear
        </Button>
      ) : null}
    </div>
  );
}
