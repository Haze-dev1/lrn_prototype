'use client';

import { useState } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { ApiError } from '@/lib/api/client';
import { startCheckout, type PlanId } from '@/lib/api/billing';

export interface CheckoutButtonProps {
  plan: PlanId;
  label: string;
  variant?: 'primary' | 'secondary';
  /** Rendered disabled with a reason, for a plan that cannot be bought right now. */
  disabledReason?: string | null;
}

/**
 * Starts a hosted checkout and hands the browser to the payment provider.
 *
 * A full navigation rather than a router push: the destination is the provider's domain, and a
 * client-side transition cannot go there. `window.location.assign` also leaves the current page
 * in history, so a student who backs out of checkout returns to pricing rather than to nothing.
 *
 * The button stays busy after a successful call and is never re-enabled. Re-enabling it during
 * the navigation would give a second click a window in which to open a second checkout session.
 */
export function CheckoutButton({
  plan,
  label,
  variant = 'primary',
  disabledReason = null,
}: CheckoutButtonProps) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleClick() {
    setError(null);
    setPending(true);
    try {
      const { url } = await startCheckout(plan);
      window.location.assign(url);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : 'Checkout could not be started. Please try again.',
      );
      setPending(false);
    }
  }

  if (disabledReason) {
    return (
      <div className="space-y-2">
        <Button variant={variant} fullWidth disabled>
          {label}
        </Button>
        <p className="text-xs text-text-muted">{disabledReason}</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <Button variant={variant} fullWidth loading={pending} onClick={handleClick}>
        {label}
      </Button>
      {error ? <Alert tone="error">{error}</Alert> : null}
    </div>
  );
}
