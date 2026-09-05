/**
 * A question's version history.
 *
 * The list carries identity and lifecycle only — never content — so opening the history of a
 * question does not ship its rubrics to the browser. Content is fetched deliberately, one version
 * at a time, when an author opens it.
 */

import Link from 'next/link';
import type { Route } from 'next';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import type { QuestionVersionSummary, VersionStatus } from '@/lib/api/admin';

const VERSION_TONE: Record<VersionStatus, BadgeTone> = {
  published: 'strong',
  draft: 'developing',
  superseded: 'neutral',
};

export interface VersionHistoryProps {
  questionId: string;
  versions: QuestionVersionSummary[];
  selectedId: string | null;
}

export function VersionHistory({ questionId, versions, selectedId }: VersionHistoryProps) {
  return (
    <section
      aria-labelledby="history-heading"
      className="rounded-[--radius-card] border border-border-subtle bg-surface-1"
    >
      <h2 id="history-heading" className="label-micro border-b border-border-subtle px-5 py-4">
        Version history
      </h2>

      {versions.length === 0 ? (
        <p className="px-5 py-6 text-sm text-text-muted">
          No versions yet. Author one to make this question gradeable.
        </p>
      ) : (
        <ul className="divide-y divide-border-subtle">
          {versions.map((version) => {
            const selected = version.id === selectedId;
            return (
              <li key={version.id}>
                <Link
                  href={`/admin/questions/${questionId}?version=${version.id}` as Route}
                  aria-current={selected ? 'true' : undefined}
                  className={[
                    'flex items-center justify-between gap-3 px-5 py-3 transition-colors',
                    selected ? 'bg-surface-2' : 'hover:bg-surface-2',
                  ].join(' ')}
                >
                  <span className="tabular text-sm text-text-primary">v{version.version}</span>
                  <Badge tone={VERSION_TONE[version.status]}>{version.status}</Badge>
                </Link>
              </li>
            );
          })}
        </ul>
      )}

      <div className="border-t border-border-subtle px-5 py-3">
        <Link
          href={`/admin/questions/${questionId}` as Route}
          className="text-sm text-accent underline-offset-4 hover:underline"
        >
          New version
        </Link>
      </div>
    </section>
  );
}
