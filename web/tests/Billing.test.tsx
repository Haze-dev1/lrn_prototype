/**
 * Billing surfaces.
 *
 * The rule these tests exist to pin is that the interface never awards access. It renders what
 * the server decided and nothing else, so the cases worth asserting are the ones where a
 * component might be tempted to decide for itself: a checkout return before the webhook has
 * landed, a 402 arriving mid-set, and an allowance meter for someone who has no allowance.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AllowanceMeter } from '@/features/billing/components/AllowanceMeter';
import { BillingPanel } from '@/features/billing/components/BillingPanel';
import { ConfirmingAccess } from '@/features/billing/components/ConfirmingAccess';
import { PaywallNotice } from '@/features/billing/components/PaywallNotice';
import { PlanCard } from '@/features/billing/components/PlanCard';
import { UpgradePrompt } from '@/features/billing/components/UpgradePrompt';
import { paywallDetail, type Entitlement, type Plan } from '@/lib/api/billing';
import { ApiError } from '@/lib/api/client';
import type { CategoryResult } from '@/lib/api/sessions';

const fetchEntitlement = vi.fn();
const startCheckout = vi.fn();
vi.mock('@/lib/api/billing', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/billing')>();
  return {
    ...actual,
    fetchEntitlement: () => fetchEntitlement(),
    startCheckout: (...args: unknown[]) => startCheckout(...args),
  };
});

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

function entitlement(overrides: Partial<Entitlement> = {}): Entitlement {
  return {
    plan: 'free',
    is_paid: false,
    active_until: null,
    expired_at: null,
    cancel_at_period_end: false,
    can_manage_billing: false,
    can_start_practice: true,
    can_grade_answer: true,
    can_start_new_diagnostic: true,
    usage: {
      diagnostics_taken: 1,
      practice_sessions_used: 1,
      practice_sessions_limit: 3,
      practice_sessions_remaining: 2,
      graded_last_24h: 4,
      daily_grade_limit: 15,
      grades_remaining_today: 11,
    },
    ...overrides,
  };
}

function plan(overrides: Partial<Plan> = {}): Plan {
  return {
    plan: 'season_pass',
    name: 'Season Pass',
    tagline: 'One recruiting season. One payment.',
    features: ['Everything in Pro', '120 days of access from purchase'],
    purchasable: true,
    one_time: true,
    duration_days: 120,
    ...overrides,
  };
}

function categoryResult(overrides: Partial<CategoryResult> = {}): CategoryResult {
  return {
    slug: 'valuation',
    name: 'Valuation',
    score: 54,
    previous_score: null,
    evidence_count: 3,
    session_scores: [50, 54, 58],
    answered: 3,
    missed_concepts: ['net_debt', 'cash'],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('paywallDetail', () => {
  it('reads the structured body of a 402', () => {
    const detail = paywallDetail(
      new ApiError(402, 'limit', {
        reason: 'practice_limit_reached',
        message: 'You have used all 3 free practice sets.',
        used: 3,
        limit: 3,
        upgrade_url: '/pricing',
      }),
    );

    expect(detail?.reason).toBe('practice_limit_reached');
    expect(detail?.limit).toBe(3);
  });

  it('does not treat a server error as a paywall', () => {
    // A 500 rendered as an upgrade prompt would tell a student to pay for a bug.
    expect(paywallDetail(new ApiError(500, 'Internal Server Error'))).toBeNull();
    expect(paywallDetail(new Error('network'))).toBeNull();
  });

  it('rejects a 402 whose body is not the expected shape', () => {
    expect(paywallDetail(new ApiError(402, 'nope', 'just a string'))).toBeNull();
  });
});

describe('PaywallNotice', () => {
  it('states the limit before it offers anything', () => {
    render(
      <PaywallNotice
        detail={{
          reason: 'practice_limit_reached',
          message: 'You have used all 3 free practice sets.',
          used: 3,
          limit: 3,
          upgrade_url: '/pricing',
        }}
      />,
    );

    expect(screen.getByText(/used all 3 free practice sets/i)).toBeInTheDocument();
    expect(screen.getByText('3 of 3 used')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /see plans/i })).toHaveAttribute('href', '/pricing');
  });

  it('omits the meter when the refusal carries no numbers', () => {
    render(
      <PaywallNotice
        detail={{
          reason: 'other',
          message: 'Not available.',
          used: null,
          limit: null,
          upgrade_url: '/pricing',
        }}
      />,
    );

    expect(screen.queryByText(/used$/)).not.toBeInTheDocument();
  });
});

describe('AllowanceMeter', () => {
  it('shows what is left before it runs out', () => {
    render(<AllowanceMeter entitlement={entitlement()} kind="practice" />);

    expect(screen.getByText(/2 of 3 free practice sets left/i)).toBeInTheDocument();
  });

  it('renders nothing for a paid account', () => {
    // A meter reading "unlimited" is noise on every page it would appear on.
    const { container } = render(
      <AllowanceMeter entitlement={entitlement({ is_paid: true, plan: 'pro_monthly' })} kind="practice" />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it('says the allowance is spent rather than showing a zero', () => {
    render(
      <AllowanceMeter
        entitlement={entitlement({
          usage: { ...entitlement().usage, practice_sessions_remaining: 0 },
        })}
        kind="practice"
      />,
    );

    expect(screen.getByText(/used every free practice set/i)).toBeInTheDocument();
  });

  it('scopes the grading allowance to today', () => {
    render(<AllowanceMeter entitlement={entitlement()} kind="grading" />);

    expect(screen.getByText(/11 of 15 free graded answers left today/i)).toBeInTheDocument();
  });
});

describe('PlanCard', () => {
  it('offers checkout to a signed-in free user', () => {
    render(<PlanCard plan={plan()} entitlement={entitlement()} billingEnabled />);

    expect(screen.getByRole('button', { name: /get the season pass/i })).toBeEnabled();
  });

  it('sends an anonymous visitor to sign up rather than to checkout', () => {
    render(<PlanCard plan={plan()} entitlement={null} billingEnabled />);

    expect(screen.getByRole('link', { name: /create an account/i })).toHaveAttribute(
      'href',
      '/signup',
    );
  });

  it('explains why a plan cannot be bought instead of showing a dead button', () => {
    render(<PlanCard plan={plan()} entitlement={entitlement()} billingEnabled={false} />);

    expect(screen.getByRole('button', { name: /get the season pass/i })).toBeDisabled();
    expect(screen.getByText(/payments are not available/i)).toBeInTheDocument();
  });

  it('does not try to sell a plan the caller already has', () => {
    render(
      <PlanCard
        plan={plan()}
        entitlement={entitlement({ is_paid: true, plan: 'season_pass' })}
        billingEnabled
      />,
    );

    expect(screen.getByText('Current')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /get the season pass/i })).not.toBeInTheDocument();
  });

  it('does not offer a second plan to someone who is already paying', () => {
    render(
      <PlanCard
        plan={plan()}
        entitlement={entitlement({ is_paid: true, plan: 'pro_monthly' })}
        billingEnabled
      />,
    );

    expect(screen.getByText(/already have access/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /get the season pass/i })).not.toBeInTheDocument();
  });
});

describe('BillingPanel', () => {
  it('shows the free allowance for an account that has never paid', () => {
    render(<BillingPanel entitlement={entitlement()} />);

    expect(screen.getByText('Free')).toBeInTheDocument();
    expect(screen.getByText(/2 of 3 practice sets left/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'See plans' })).toBeInTheDocument();
  });

  it('says when a cancelled subscription actually ends', () => {
    render(
      <BillingPanel
        entitlement={entitlement({
          plan: 'pro_monthly',
          is_paid: true,
          cancel_at_period_end: true,
          active_until: '2026-10-01T00:00:00Z',
          can_manage_billing: true,
        })}
      />,
    );

    expect(screen.getByText(/set to end on/i)).toBeInTheDocument();
    expect(screen.getByText(/keep full access until then/i)).toBeInTheDocument();
  });

  it('names the date access ended and offers renewal, not a first-time pitch', () => {
    render(
      <BillingPanel
        entitlement={entitlement({ expired_at: '2026-08-01T00:00:00Z' })}
      />,
    );

    expect(screen.getByText(/your access ended on/i)).toBeInTheDocument();
    expect(screen.getByText(/still here/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Renew access' })).toBeInTheDocument();
  });

  it('hides the portal for someone with no billing account', () => {
    render(<BillingPanel entitlement={entitlement()} />);

    expect(screen.queryByRole('button', { name: /manage billing/i })).not.toBeInTheDocument();
  });
});

describe('UpgradePrompt', () => {
  it('names the weakest category and counts real missed concepts', () => {
    render(
      <UpgradePrompt
        entitlement={entitlement()}
        categories={[
          categoryResult(),
          categoryResult({ slug: 'accounting', name: 'Accounting', score: 81, missed_concepts: [] }),
        ]}
      />,
    );

    expect(screen.getByText(/you found the gaps/i)).toBeInTheDocument();
    expect(screen.getByText(/Valuation is your weakest category at 54/)).toBeInTheDocument();
    expect(screen.getByText(/2 concepts you missed/)).toBeInTheDocument();
  });

  it('ignores unmeasured categories when picking the weakest', () => {
    // An unmeasured category has no score to be weakest at; treating it as one would name a
    // category the student never answered.
    render(
      <UpgradePrompt
        entitlement={entitlement()}
        categories={[
          categoryResult({ score: 70 }),
          categoryResult({ slug: 'lbo', name: 'LBO', score: 0, evidence_count: 0 }),
        ]}
      />,
    );

    expect(screen.getByText(/Valuation is your weakest category at 70/)).toBeInTheDocument();
  });

  it('renders nothing for a paid account', () => {
    const { container } = render(
      <UpgradePrompt
        entitlement={entitlement({ is_paid: true, plan: 'pro_monthly' })}
        categories={[categoryResult()]}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});

describe('ConfirmingAccess', () => {
  it('confirms immediately when the webhook already landed', () => {
    render(<ConfirmingAccess initial={entitlement({ is_paid: true, plan: 'season_pass' })} />);

    expect(screen.getByText(/you have full access/i)).toBeInTheDocument();
    expect(fetchEntitlement).not.toHaveBeenCalled();
  });

  it('waits rather than awarding access the browser cannot grant', () => {
    render(<ConfirmingAccess initial={entitlement()} />);

    expect(screen.getByText(/confirming your access/i)).toBeInTheDocument();
    expect(screen.queryByText(/you have full access/i)).not.toBeInTheDocument();
  });

  it('flips to confirmed once the server agrees', async () => {
    fetchEntitlement.mockResolvedValue(entitlement({ is_paid: true, plan: 'season_pass' }));

    render(<ConfirmingAccess initial={entitlement()} />);

    await waitFor(
      () => expect(screen.getByText(/you have full access/i)).toBeInTheDocument(),
      { timeout: 5_000 },
    );
  });

  it('keeps polling when a poll fails, because a failed poll is not a failed payment', async () => {
    fetchEntitlement.mockRejectedValueOnce(new ApiError(503, 'down'));
    fetchEntitlement.mockResolvedValue(entitlement({ is_paid: true, plan: 'season_pass' }));

    render(<ConfirmingAccess initial={entitlement()} />);

    await waitFor(
      () => expect(screen.getByText(/you have full access/i)).toBeInTheDocument(),
      { timeout: 8_000 },
    );
  });
});

describe('CheckoutButton', () => {
  it('does not re-enable itself after starting checkout', async () => {
    // Re-enabling during the navigation would give a second click a window to open a second
    // checkout session.
    const assign = vi.fn();
    vi.stubGlobal('location', { assign });
    startCheckout.mockResolvedValue({ url: 'https://checkout.example/session' });

    render(<PlanCard plan={plan()} entitlement={entitlement()} billingEnabled />);
    const button = screen.getByRole('button', { name: /get the season pass/i });
    fireEvent.click(button);

    await waitFor(() => expect(assign).toHaveBeenCalledWith('https://checkout.example/session'));
    expect(button).toBeDisabled();
    vi.unstubAllGlobals();
  });

  it('surfaces a refusal without navigating anywhere', async () => {
    const assign = vi.fn();
    vi.stubGlobal('location', { assign });
    startCheckout.mockRejectedValue(new ApiError(409, 'You already have access.'));

    render(<PlanCard plan={plan()} entitlement={entitlement()} billingEnabled />);
    fireEvent.click(screen.getByRole('button', { name: /get the season pass/i }));

    await waitFor(() =>
      expect(screen.getByText(/you already have access/i)).toBeInTheDocument(),
    );
    expect(assign).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
