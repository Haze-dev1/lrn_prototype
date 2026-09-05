'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { Input } from '@/components/ui/Input';
import { deleteAccount, exportData } from '@/lib/api/auth';
import { ApiError } from '@/lib/api/client';

export interface DataControlsProps {
  /** Google-only accounts have no password to confirm with. */
  hasPassword: boolean;
}

/** Data export and permanent account deletion. */
export function DataControls({ hasPassword }: DataControlsProps) {
  const router = useRouter();
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const [confirming, setConfirming] = useState(false);
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function handleExport() {
    setExportError(null);
    setExporting(true);
    try {
      const data = await exportData();
      // Built and revoked in the browser: the export contains the student's own answers, so it
      // never passes through a third-party host or a shareable URL.
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `lrn-data-export-${new Date().toISOString().slice(0, 10)}.json`;
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      setExportError('We could not prepare your export. Please try again.');
    } finally {
      setExporting(false);
    }
  }

  async function handleDelete() {
    setDeleteError(null);
    setDeleting(true);
    try {
      await deleteAccount(hasPassword ? password : null);
      router.replace('/');
      router.refresh();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setDeleteError('That password is not correct.');
      } else {
        setDeleteError('We could not delete your account. Please try again.');
      }
      setDeleting(false);
    }
  }

  return (
    <>
      <section
        aria-labelledby="export-heading"
        className="rounded-[--radius-card] border border-border-subtle bg-surface-1 p-6"
      >
        <h2 id="export-heading" className="label-micro">
          Your data
        </h2>
        <p className="mt-3 text-sm leading-relaxed text-text-secondary">
          Download everything your account holds — your profile, sessions, answers, grades and
          mastery scores — as a JSON file.
        </p>
        {exportError ? (
          <div className="mt-4">
            <Alert tone="error">{exportError}</Alert>
          </div>
        ) : null}
        <div className="mt-5">
          <Button variant="secondary" loading={exporting} onClick={handleExport}>
            {exporting ? 'Preparing export' : 'Download my data'}
          </Button>
        </div>
      </section>

      <section
        aria-labelledby="delete-heading"
        className="rounded-[--radius-card] border border-band-needs-work/30 bg-surface-1 p-6"
      >
        <h2 id="delete-heading" className="label-micro text-band-needs-work">
          Delete account
        </h2>
        <p className="mt-3 text-sm leading-relaxed text-text-secondary">
          Permanently deletes your account and everything in it, including every answer you have
          written and every grade you have received. This cannot be undone.
        </p>

        {deleteError ? (
          <div className="mt-4">
            <Alert tone="error">{deleteError}</Alert>
          </div>
        ) : null}

        {!confirming ? (
          <div className="mt-5">
            <Button variant="secondary" onClick={() => setConfirming(true)}>
              Delete my account
            </Button>
          </div>
        ) : (
          <div className="mt-5 space-y-4">
            {hasPassword ? (
              <Field id="delete-password" label="Confirm your password">
                <Input
                  id="delete-password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  disabled={deleting}
                />
              </Field>
            ) : null}

            <Field
              id="delete-confirmation"
              label="Type DELETE to confirm"
              hint="This is your last chance to change your mind."
            >
              <Input
                id="delete-confirmation"
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
                disabled={deleting}
                placeholder="DELETE"
              />
            </Field>

            <div className="flex flex-wrap gap-3">
              <Button
                loading={deleting}
                disabled={confirmation !== 'DELETE' || (hasPassword && password === '')}
                onClick={handleDelete}
              >
                {deleting ? 'Deleting' : 'Permanently delete'}
              </Button>
              <Button
                variant="ghost"
                disabled={deleting}
                onClick={() => {
                  setConfirming(false);
                  setConfirmation('');
                  setPassword('');
                  setDeleteError(null);
                }}
              >
                Cancel
              </Button>
            </div>
          </div>
        )}
      </section>
    </>
  );
}
