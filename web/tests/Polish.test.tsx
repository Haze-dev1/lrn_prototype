/**
 * The quality pass, pinned.
 *
 * These are regressions rather than features: each one is a defect the audit found in a surface
 * that already "worked". A meter that reported "53 of 15 used", a session with no way out, a 404
 * that offered nothing to click. None of them would fail a build, and all of them are what the
 * product feels like to use.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { SessionExit } from '@/components/layout/SessionExit';
import RouteError from '@/app/error';
import NotFound from '@/app/not-found';
import { AllowanceMeter } from '@/features/billing/components/AllowanceMeter';
import { PaywallNotice } from '@/features/billing/components/PaywallNotice';
import { GradedAnswerDemo } from '@/features/marketing/components/GradedAnswerDemo';
import { MasteryDemo } from '@/features/marketing/components/MasteryDemo';
import { ProductLoop } from '@/features/marketing/components/ProductLoop';
import type { Entitlement } from '@/lib/api/billing';

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

describe('PaywallNotice meter', () => {
  it('never reports more used than the allowance holds', () => {
    // Found in the browser: an account with 53 graded answers against a limit of 15 rendered
    // "53 of 15 used", which reads as broken arithmetic and discredits the number beside it.
    render(
      <PaywallNotice
        detail={{
          reason: 'grading_limit_reached',
          message: 'You have used all 15 graded answers for today.',
          used: 53,
          limit: 15,
          upgrade_url: '/pricing',
        }}
      />,
    );

    expect(screen.getByText('15 of 15 used')).toBeInTheDocument();
    expect(screen.queryByText('53 of 15 used')).not.toBeInTheDocument();
  });

  it('reports an ordinary partial usage unchanged', () => {
    render(
      <PaywallNotice
        detail={{
          reason: 'practice_limit_reached',
          message: 'Limit reached.',
          used: 3,
          limit: 3,
          upgrade_url: '/pricing',
        }}
      />,
    );

    expect(screen.getByText('3 of 3 used')).toBeInTheDocument();
  });
});

describe('AllowanceMeter', () => {
  it('never reports more remaining than the allowance holds', () => {
    render(
      <AllowanceMeter
        entitlement={entitlement({
          usage: { ...entitlement().usage, practice_sessions_remaining: 99 },
        })}
        kind="practice"
      />,
    );

    expect(screen.getByText(/3 of 3 free practice sets left/i)).toBeInTheDocument();
  });
});

describe('SessionExit', () => {
  it('gives a diagnostic an exit that promises resumption', () => {
    // The runners render without the application shell so the student has nothing to look at but
    // the question. That is a reason to remove navigation, not a reason to remove every way out.
    render(<SessionExit kind="diagnostic" />);

    const link = screen.getByRole('link', { name: /save and exit/i });
    expect(link).toHaveAttribute('href', '/dashboard');
    expect(link).toHaveAttribute('title', expect.stringMatching(/come back to this question/i));
  });

  it('does not promise a practice set will resume, because it does not', () => {
    render(<SessionExit kind="practice" />);

    expect(screen.getByRole('link', { name: /leave this set/i })).toBeInTheDocument();
  });
});

describe('NotFound', () => {
  it('offers a way out rather than a status code', () => {
    render(<NotFound />);

    expect(screen.getByRole('link', { name: /go to your dashboard/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /review your answers/i })).toBeInTheDocument();
  });
});

describe('RouteError', () => {
  it('never renders the exception message', () => {
    // The message can carry a query, a path or an upstream provider's wording.
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const error = Object.assign(new Error('connect ECONNREFUSED 10.0.0.4:5432'), {
      digest: 'abc123',
    });

    render(<RouteError error={error} reset={() => {}} />);

    expect(screen.queryByText(/ECONNREFUSED/)).not.toBeInTheDocument();
    expect(screen.getByText(/could not be loaded/i)).toBeInTheDocument();
    expect(screen.getByText(/Reference abc123/)).toBeInTheDocument();
  });

  it('offers both a retry and a way out', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const reset = vi.fn();

    render(<RouteError error={new Error('boom')} reset={reset} />);

    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /go to your dashboard/i })).toBeInTheDocument();
  });
});

describe('Landing page', () => {
  it('shows a graded answer rather than describing one', () => {
    render(<GradedAnswerDemo />);

    expect(screen.getByText('68')).toBeInTheDocument();
    expect(screen.getByText(/developing/i)).toBeInTheDocument();
  });

  it('marks what the answer established and what it missed', () => {
    // The whole argument of the page: the grader reports absence, not just presence.
    render(<GradedAnswerDemo />);

    expect(screen.getByText('subtract net debt')).toBeInTheDocument();
    expect(screen.getByText('minority interest')).toBeInTheDocument();
    expect(screen.getByText(/not found/i)).toBeInTheDocument();
  });

  it('carries no rubric language a real question would leak', () => {
    const { container } = render(<GradedAnswerDemo />);

    expect(container.textContent?.toLowerCase()).not.toContain('ideal answer');
  });

  it('renders an unmeasured category as unmeasured, not as zero', () => {
    // The same rule the product enforces everywhere: "not asked" and "did badly" are different
    // claims, and the landing page must not teach the reader to expect the wrong one.
    render(<MasteryDemo />);

    expect(screen.getByText('Not measured yet')).toBeInTheDocument();
    expect(screen.getByText('Markets, deals & judgment')).toBeInTheDocument();
  });

  it('closes the loop it claims to be a loop', () => {
    render(<ProductLoop />);

    expect(screen.getByText(/→ 01/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Improve' })).toBeInTheDocument();
  });
});
