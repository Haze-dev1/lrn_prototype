'use client';

import { useState } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { ApiError } from '@/lib/api/client';
import { openBillingPortal } from '@/lib/api/billing';

/**
 * Opens the payment provider's Customer Portal.
 *
 * Cancellation, payment methods and invoices all live there rather than here. That is not
 * laziness: it means no card number ever reaches this system, a cancellation is recorded by the
 * provider that has to honour it, and there is no in-house cancel flow that could get out of step
 * with what the provider believes.
 */
export function ManageBillingButton() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleClick() {
    setError(null);
    setPending(true);
    try {
      const { url } = await openBillingPortal();
      window.location.assign(url);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : 'Billing management is unavailable. Please try again.',
      );
      setPending(false);
    }
  }

  return (
    <div className="space-y-2">
      <Button variant="secondary" loading={pending} onClick={handleClick}>
        Manage billing
      </Button>
      {error ? <Alert tone="error">{error}</Alert> : null}
    </div>
  );
}
