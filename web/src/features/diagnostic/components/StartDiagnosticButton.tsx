'use client';

import { useRouter } from 'next/navigation';
import type { Route } from 'next';
import { useState } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { PaywallNotice } from '@/features/billing/components/PaywallNotice';
import { paywallDetail, type PaywallDetail } from '@/lib/api/billing';
import { ApiError } from '@/lib/api/client';
import { startDiagnostic } from '@/lib/api/sessions';

export interface StartDiagnosticButtonProps {
  label: string;
}

/**
 * Starts or resumes the diagnostic and navigates into it.
 *
 * A button rather than a link, because starting composes a session server-side and a GET must not
 * have that side effect. Resuming goes through exactly the same call: the server returns the
 * in-progress session if one exists, so this component does not need to know which case it is in.
 *
 * A free account gets one diagnostic, so a *second* one comes back as a 402. Resuming never does,
 * which is why that case is rendered as an upgrade prompt rather than an error.
 */
export function StartDiagnosticButton({ label }: StartDiagnosticButtonProps) {
  const router = useRouter();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [paywall, setPaywall] = useState<PaywallDetail | null>(null);

  async function handleStart() {
    setError(null);
    setPaywall(null);
    setStarting(true);
    try {
      const session = await startDiagnostic();
      router.push(`/diagnostic/${session.id}` as Route);
    } catch (caught) {
      const limit = paywallDetail(caught);
      if (limit) {
        setPaywall(limit);
      } else {
        setError(
          caught instanceof ApiError ? caught.message : 'Could not start. Please try again.',
        );
      }
      setStarting(false);
    }
  }

  return (
    <div className="space-y-3">
      {error ? <Alert tone="error">{error}</Alert> : null}
      {paywall ? <PaywallNotice detail={paywall} heading="Diagnostic" /> : null}
      <Button size="lg" loading={starting} disabled={paywall !== null} onClick={handleStart}>
        {label}
      </Button>
    </div>
  );
}
