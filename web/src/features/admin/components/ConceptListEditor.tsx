'use client';

import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import type { ConceptEntry } from '@/lib/api/admin';

export interface ConceptListEditorProps {
  id: string;
  label: string;
  hint: string;
  entries: ConceptEntry[];
  onChange: (entries: ConceptEntry[]) => void;
  disabled?: boolean;
}

/**
 * Editor for a keyed concept list — expected concepts or common mistakes.
 *
 * The key and the label are edited separately because they do different jobs: the key is recorded
 * against every attempt and aggregated into mastery, so it must stay stable, while the label is
 * display copy that can be improved freely. Collapsing them into one field would mean every
 * wording fix silently forked a student's concept history.
 */
export function ConceptListEditor({
  id,
  label,
  hint,
  entries,
  onChange,
  disabled = false,
}: ConceptListEditorProps) {
  function update(index: number, patch: Partial<ConceptEntry>) {
    onChange(entries.map((entry, position) => (position === index ? { ...entry, ...patch } : entry)));
  }

  return (
    <fieldset className="space-y-2" disabled={disabled}>
      <legend className="text-sm font-medium text-text-primary">{label}</legend>
      <p className="text-xs text-text-muted">{hint}</p>

      {entries.length === 0 ? (
        <p className="py-2 text-xs text-text-muted">None yet.</p>
      ) : (
        <ul className="space-y-2">
          {entries.map((entry, index) => (
            <li key={index} className="flex items-start gap-2">
              <div className="w-44 shrink-0">
                <label htmlFor={`${id}-key-${index}`} className="sr-only">
                  {label} key {index + 1}
                </label>
                <Input
                  id={`${id}-key-${index}`}
                  value={entry.key}
                  placeholder="stable_key"
                  maxLength={64}
                  onChange={(event) => update(index, { key: event.target.value })}
                />
              </div>
              <div className="flex-1">
                <label htmlFor={`${id}-label-${index}`} className="sr-only">
                  {label} description {index + 1}
                </label>
                <Input
                  id={`${id}-label-${index}`}
                  value={entry.label}
                  placeholder="What the student is expected to show"
                  maxLength={200}
                  onChange={(event) => update(index, { label: event.target.value })}
                />
              </div>
              <Button
                type="button"
                variant="ghost"
                size="md"
                onClick={() => onChange(entries.filter((_, position) => position !== index))}
                aria-label={`Remove ${label.toLowerCase()} ${index + 1}`}
              >
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}

      <Button
        type="button"
        variant="secondary"
        size="sm"
        onClick={() => onChange([...entries, { key: '', label: '' }])}
      >
        Add
      </Button>
    </fieldset>
  );
}
