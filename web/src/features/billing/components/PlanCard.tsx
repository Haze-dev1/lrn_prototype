import { CheckoutButton } from '@/features/billing/components/CheckoutButton';
import type { Entitlement, Plan } from '@/lib/api/billing';

export interface PlanCardProps {
  plan: Plan;
  /** The caller's access, or null when they are not signed in. */
  entitlement: Entitlement | null;
  billingEnabled: boolean;
  /** Draws the card as the recommended choice. */
  emphasised?: boolean;
}

/**
 * One plan on the pricing page.
 *
 * The Season Pass is the emphasised card. That is a product decision, not a visual one: students
 * are buying for a recruiting cycle they can see the end of, and a one-time purchase for that
 * cycle is easier to say yes to than an open-ended subscription they will have to remember to
 * cancel.
 *
 * Every state a plan can be in is rendered explicitly — current plan, unavailable, not signed in,
 * payments not configured — because a pricing card with a dead button is worse than one that says
 * why it cannot be clicked.
 */
export function PlanCard({ plan, entitlement, billingEnabled, emphasised = false }: PlanCardProps) {
  const isFree = plan.plan === 'free';
  const isCurrent = entitlement
    ? entitlement.plan === plan.plan
    : false;
  const signedIn = entitlement !== null;

  const unavailable = !billingEnabled
    ? 'Payments are not available right now.'
    : !plan.purchasable
      ? 'This plan is not on sale at the moment.'
      : null;

  return (
    <div
      className={[
        'flex flex-col rounded-[--radius-card] border p-6',
        emphasised
          ? 'border-accent bg-surface-2'
          : 'border-border-subtle bg-surface-1',
      ].join(' ')}
    >
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-lg font-semibold text-text-primary">{plan.name}</h2>
        {isCurrent ? (
          <span className="label-micro text-band-strong">Current</span>
        ) : emphasised ? (
          <span className="label-micro text-accent">Recruiting season</span>
        ) : null}
      </div>

      <p className="mt-2 text-sm text-text-secondary">{plan.tagline}</p>

      <ul className="mt-5 flex-1 space-y-2.5">
        {plan.features.map((feature) => (
          <li key={feature} className="flex gap-2.5 text-sm text-text-secondary">
            <span aria-hidden="true" className="text-accent">
              —
            </span>
            {feature}
          </li>
        ))}
      </ul>

      <div className="mt-6">
        {isCurrent ? (
          <p className="text-sm text-text-muted">
            {isFree ? 'You are on the free tier.' : 'This is your current plan.'}
          </p>
        ) : isFree ? (
          <p className="text-sm text-text-muted">
            Included with every account. No card needed.
          </p>
        ) : !signedIn ? (
          <a
            href="/signup"
            className="inline-flex h-10 w-full items-center justify-center rounded-md bg-text-primary px-4 text-sm font-medium text-text-inverse transition-colors hover:bg-white"
          >
            Create an account
          </a>
        ) : entitlement?.is_paid ? (
          <p className="text-sm text-text-muted">
            You already have access. Change plans from your account.
          </p>
        ) : (
          <CheckoutButton
            plan={plan.plan}
            label={plan.one_time ? `Get the ${plan.name}` : `Go ${plan.name}`}
            variant={emphasised ? 'primary' : 'secondary'}
            disabledReason={unavailable}
          />
        )}
      </div>
    </div>
  );
}
