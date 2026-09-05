'use client';

import { useState } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { setRecruitingConsent, type Profile } from '@/lib/api/auth';

export interface ConsentControlProps {
  profile: Profile | null;
}

/**
 * Recruiting consent control.
 *
 * Consent is off unless the student turns it on, the explanation sits next to the control rather
 * than behind a link, and withdrawing is the same single action as granting.
 */
export function ConsentControl({ profile }: ConsentControlProps) {
  const [granted, setGranted] = useState(profile?.recruiting_consent ?? false);
  const [updatedAt, setUpdatedAt] = useState(profile?.recruiting_consent_updated_at ?? null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function toggle() {
    setError(null);
    setSaving(true);
    try {
      const updated = await setRecruitingConsent(!granted);
      setGranted(updated.profile?.recruiting_consent ?? false);
      setUpdatedAt(updated.profile?.recruiting_consent_updated_at ?? null);
    } catch {
      setError('We could not update your preference. Please try again.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <section
      aria-labelledby="consent-heading"
      className="rounded-[--radius-card] border border-border-subtle bg-surface-1 p-6"
    >
      <h2 id="consent-heading" className="label-micro">
        Recruiting visibility
      </h2>

      <p className="mt-3 text-sm leading-relaxed text-text-secondary">
        LRN can make your category mastery visible to recruiters looking for candidates. Your
        answers, your scores on individual questions, and your email address are never shared.
        This is off unless you turn it on, and you can turn it off again at any time.
      </p>

      {error ? (
        <div className="mt-4">
          <Alert tone="error">{error}</Alert>
        </div>
      ) : null}

      <div className="mt-5 flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="font-mono text-sm text-text-primary">
            {granted ? 'Visible to recruiters' : 'Not visible to recruiters'}
          </p>
          {updatedAt ? (
            <p className="mt-0.5 text-xs text-text-muted">
              Last changed {new Date(updatedAt).toLocaleDateString()}
            </p>
          ) : null}
        </div>

        <Button
          variant={granted ? 'secondary' : 'primary'}
          loading={saving}
          onClick={toggle}
          aria-pressed={granted}
        >
          {granted ? 'Turn off' : 'Turn on'}
        </Button>
      </div>
    </section>
  );
}
