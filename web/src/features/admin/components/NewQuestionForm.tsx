'use client';

import { useRouter } from 'next/navigation';
import type { Route } from 'next';
import { useState, type FormEvent } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { ApiError } from '@/lib/api/client';
import { createQuestion } from '@/lib/api/admin';
import type { Category } from '@/lib/api/questions';

export interface NewQuestionFormProps {
  categories: Category[];
}

/**
 * Create a question's identity and taxonomy.
 *
 * Deliberately taxonomy only. Content is authored on the detail page, where the version editor
 * can show validation, history, and the publish gate together — splitting the form across two
 * steps keeps the moment of authoring a rubric in the one place that can explain it.
 */
export function NewQuestionForm({ categories }: NewQuestionFormProps) {
  const router = useRouter();
  const [categorySlug, setCategorySlug] = useState(categories[0]?.slug ?? '');
  const [subcategory, setSubcategory] = useState('');
  const [sourceKey, setSourceKey] = useState('');
  const [difficulty, setDifficulty] = useState('3');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const created = await createQuestion({
        category_slug: categorySlug,
        subcategory: subcategory.trim() === '' ? null : subcategory.trim(),
        source_key: sourceKey.trim() === '' ? null : sourceKey.trim(),
        difficulty: Number(difficulty),
      });
      router.push(`/admin/questions/${created.id}` as Route);
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : 'Something went wrong. Please try again.',
      );
      setSaving(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-5 rounded-[--radius-card] border border-border-subtle bg-surface-1 p-6"
      noValidate
    >
      {error ? <Alert tone="error">{error}</Alert> : null}

      <Field id="new-category" label="Category">
        <Select
          id="new-category"
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

      <Field id="new-subcategory" label="Subcategory" hint="Optional, e.g. 'Statement linkages'.">
        <Input
          id="new-subcategory"
          maxLength={200}
          value={subcategory}
          onChange={(event) => setSubcategory(event.target.value)}
          disabled={saving}
        />
      </Field>

      <Field
        id="new-difficulty"
        label="Difficulty"
        hint="1 is a foundational opener, 5 is a judgement question."
      >
        <Select
          id="new-difficulty"
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

      <Field
        id="new-source-key"
        label="Content key"
        hint="Optional. Set this to manage the question from the authored content file; it must be unique."
      >
        <Input
          id="new-source-key"
          maxLength={120}
          placeholder="acc-006-working-capital"
          value={sourceKey}
          onChange={(event) => setSourceKey(event.target.value)}
          disabled={saving}
        />
      </Field>

      <div className="border-t border-border-subtle pt-5">
        <Button type="submit" loading={saving} disabled={categorySlug === ''}>
          Create and author content
        </Button>
        <p className="mt-2 text-xs text-text-muted">
          The question is created as a draft. You will author its prompt and rubric next.
        </p>
      </div>
    </form>
  );
}
