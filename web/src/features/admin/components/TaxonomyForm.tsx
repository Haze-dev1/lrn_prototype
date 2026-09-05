'use client';

import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { ApiError } from '@/lib/api/client';
import { updateQuestion, type AdminQuestionDetail } from '@/lib/api/admin';
import type { Category } from '@/lib/api/questions';

export interface TaxonomyFormProps {
  question: AdminQuestionDetail;
  categories: Category[];
}

/**
 * Edit a question's category, subcategory and difficulty.
 *
 * Taxonomy is mutable while grading content is not: recategorising changes which weakness the
 * question counts toward from now on, but it cannot change what a past grade meant.
 */
export function TaxonomyForm({ question, categories }: TaxonomyFormProps) {
  const router = useRouter();
  const [categorySlug, setCategorySlug] = useState(question.category_slug);
  const [subcategory, setSubcategory] = useState(question.subcategory ?? '');
  const [difficulty, setDifficulty] = useState(String(question.difficulty));
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<'idle' | 'saved'>('idle');
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus('idle');
    setError(null);
    setSaving(true);
    try {
      await updateQuestion(question.id, {
        category_slug: categorySlug,
        subcategory: subcategory.trim() === '' ? null : subcategory.trim(),
        difficulty: Number(difficulty),
      });
      setStatus('saved');
      router.refresh();
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : 'Something went wrong. Please try again.',
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <section
      aria-labelledby="taxonomy-heading"
      className="rounded-[--radius-card] border border-border-subtle bg-surface-1 p-5"
    >
      <h2 id="taxonomy-heading" className="label-micro">
        Taxonomy
      </h2>

      <form onSubmit={handleSubmit} className="mt-4 space-y-4" noValidate>
        {status === 'saved' ? <Alert tone="success">Saved.</Alert> : null}
        {error ? <Alert tone="error">{error}</Alert> : null}

        <Field id="taxonomy-category" label="Category">
          <Select
            id="taxonomy-category"
            value={categorySlug}
            onChange={(event) => setCategorySlug(event.target.value)}
            disabled={saving}
          >
            {categories.map((category) => (
              <option key={category.slug} value={category.slug}>
                {category.name}
              </option>
            ))}
          </Select>
        </Field>

        <Field id="taxonomy-subcategory" label="Subcategory" hint="Optional.">
          <Input
            id="taxonomy-subcategory"
            maxLength={200}
            value={subcategory}
            onChange={(event) => setSubcategory(event.target.value)}
            disabled={saving}
          />
        </Field>

        <Field id="taxonomy-difficulty" label="Difficulty" hint="1 is foundational, 5 is hardest.">
          <Select
            id="taxonomy-difficulty"
            value={difficulty}
            onChange={(event) => setDifficulty(event.target.value)}
            disabled={saving}
          >
            {[1, 2, 3, 4, 5].map((level) => (
              <option key={level} value={level}>
                Level {level}
              </option>
            ))}
          </Select>
        </Field>

        <Button type="submit" variant="secondary" size="sm" loading={saving}>
          Save taxonomy
        </Button>
      </form>
    </section>
  );
}
