/**
 * The question list.
 *
 * A row's job is to answer whether this question is live and gradeable, so status and published
 * version carry the emphasis. The prompt is deliberately absent: the list is fetched constantly
 * and there is no reason for rubric-adjacent content to travel with it.
 */

import Link from 'next/link';
import type { Route } from 'next';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import type { AdminQuestion, QuestionStatus } from '@/lib/api/admin';
import type { Category } from '@/lib/api/questions';

const STATUS_TONE: Record<QuestionStatus, BadgeTone> = {
  active: 'strong',
  draft: 'developing',
  retired: 'neutral',
};

export interface QuestionTableProps {
  questions: AdminQuestion[];
  categories: Category[];
}

export function QuestionTable({ questions, categories }: QuestionTableProps) {
  const names = new Map(categories.map((category) => [category.slug, category.name]));

  if (questions.length === 0) {
    return (
      <div className="rounded-[--radius-card] border border-dashed border-border-subtle px-6 py-12 text-center">
        <p className="text-sm text-text-secondary">No questions match these filters.</p>
        <p className="mt-1 text-sm text-text-muted">
          Clear the filters, or create a question to start building the bank.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-[--radius-card] border border-border-subtle">
      <table className="w-full min-w-[44rem] border-collapse text-left">
        <thead>
          <tr className="border-b border-border-subtle bg-surface-1">
            <th scope="col" className="label-micro px-4 py-3 font-normal">
              Category
            </th>
            <th scope="col" className="label-micro px-4 py-3 font-normal">
              Key
            </th>
            <th scope="col" className="label-micro px-4 py-3 font-normal">
              Level
            </th>
            <th scope="col" className="label-micro px-4 py-3 font-normal">
              Status
            </th>
            <th scope="col" className="label-micro px-4 py-3 font-normal">
              Published
            </th>
            <th scope="col" className="label-micro px-4 py-3 text-right font-normal">
              Versions
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border-subtle">
          {questions.map((question) => (
            <tr key={question.id} className="transition-colors hover:bg-surface-1">
              <td className="px-4 py-3">
                <Link
                  href={`/admin/questions/${question.id}` as Route}
                  className="text-sm text-text-primary underline-offset-4 hover:underline"
                >
                  {names.get(question.category_slug) ?? question.category_slug}
                </Link>
                {question.subcategory ? (
                  <p className="mt-0.5 text-xs text-text-muted">{question.subcategory}</p>
                ) : null}
              </td>
              <td className="px-4 py-3">
                <span className="font-mono text-xs text-text-muted">
                  {question.source_key ?? '—'}
                </span>
              </td>
              <td className="tabular px-4 py-3 text-sm text-text-secondary">
                {question.difficulty}
              </td>
              <td className="px-4 py-3">
                <Badge tone={STATUS_TONE[question.status]}>{question.status}</Badge>
              </td>
              <td className="px-4 py-3 text-sm">
                {question.published_version ? (
                  <span className="tabular text-text-secondary">
                    v{question.published_version.version}
                  </span>
                ) : (
                  <span className="text-band-needs-work">none</span>
                )}
              </td>
              <td className="tabular px-4 py-3 text-right text-sm text-text-muted">
                {question.version_count}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
