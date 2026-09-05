'use client';

import { useState } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { setEmailPreferences, type EmailPreferences as Preferences } from '@/lib/api/auth';

export interface EmailPreferencesProps {
  initial: Preferences;
}

/**
 * Email preferences.
 *
 * Two switches, and the copy next to each says what it actually controls. The section also names
 * the mail a student *cannot* turn off and why — results and receipts are replies to something
 * they did, not a list they are on — because a preferences page that hides that is how people
 * discover it by being surprised.
 *
 * Each switch saves on its own. A "save changes" button here would let someone turn a preference
 * off, navigate away, and remain subscribed.
 */
export function EmailPreferences({ initial }: EmailPreferencesProps) {
  const [preferences, setPreferences] = useState(initial);
  const [saving, setSaving] = useState<keyof Preferences | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function toggle(key: keyof Preferences) {
    setError(null);
    setSaving(key);
    const next = { ...preferences, [key]: !preferences[key] };
    try {
      setPreferences(await setEmailPreferences(next));
    } catch {
      setError('We could not update your preference. Please try again.');
    } finally {
      setSaving(null);
    }
  }

  const rows: { key: keyof Preferences; label: string; description: string }[] = [
    {
      key: 'study_reminder_emails',
      label: 'Weekly study reminder',
      description:
        'One email a week naming your weakest category and anything due for review. Sent only when there is something specific to say.',
    },
    {
      key: 'marketing_emails_opt_in',
      label: 'Product news',
      description: 'Occasional updates about new question categories and features.',
    },
  ];

  return (
    <section
      aria-labelledby="email-heading"
      className="rounded-[--radius-card] border border-border-subtle bg-surface-1 p-6"
    >
      <h2 id="email-heading" className="label-micro">
        Email
      </h2>

      {error ? (
        <div className="mt-4">
          <Alert tone="error">{error}</Alert>
        </div>
      ) : null}

      <div className="mt-4 divide-y divide-border-subtle">
        {rows.map((row) => (
          <div
            key={row.key}
            className="flex flex-wrap items-start justify-between gap-4 py-4 first:pt-0 last:pb-0"
          >
            <div className="min-w-0 max-w-md">
              <p className="text-sm font-medium text-text-primary">{row.label}</p>
              <p className="mt-1 text-sm leading-relaxed text-text-secondary">
                {row.description}
              </p>
            </div>
            <Button
              variant="secondary"
              size="sm"
              loading={saving === row.key}
              aria-pressed={preferences[row.key]}
              onClick={() => toggle(row.key)}
            >
              {preferences[row.key] ? 'On' : 'Off'}
            </Button>
          </div>
        ))}
      </div>

      <p className="mt-4 border-t border-border-subtle pt-4 text-xs leading-relaxed text-text-muted">
        Diagnostic results and payment confirmations are always sent. They are replies to
        something you did rather than a mailing list, so there is nothing to unsubscribe from.
      </p>
    </section>
  );
}
