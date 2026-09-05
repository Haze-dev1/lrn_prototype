/**
 * Email preference surfaces.
 *
 * Two things are worth pinning. The unsubscribe page must not act on load — mail scanners fetch
 * every link in a message, and a page that unsubscribed on render would unsubscribe people who
 * never opened the email. And the preferences section must save each switch on its own, because
 * a "save changes" button lets someone turn a reminder off, navigate away, and stay subscribed.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { EmailPreferences } from '@/features/account/components/EmailPreferences';
import { UnsubscribeConfirm } from '@/features/account/components/UnsubscribeConfirm';
import type { EmailPreferences as Preferences } from '@/lib/api/auth';
import { ApiError } from '@/lib/api/client';

const setEmailPreferences = vi.fn();
const unsubscribeWithToken = vi.fn();
vi.mock('@/lib/api/auth', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/auth')>();
  return {
    ...actual,
    setEmailPreferences: (...args: unknown[]) => setEmailPreferences(...args),
    unsubscribeWithToken: (...args: unknown[]) => unsubscribeWithToken(...args),
  };
});

function preferences(overrides: Partial<Preferences> = {}): Preferences {
  return { study_reminder_emails: true, marketing_emails_opt_in: false, ...overrides };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('UnsubscribeConfirm', () => {
  it('does not unsubscribe on render', () => {
    // A mail scanner opening the link must not change anything.
    render(<UnsubscribeConfirm token="tok" />);

    expect(unsubscribeWithToken).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: /turn off study reminders/i })).toBeInTheDocument();
  });

  it('unsubscribes on an explicit click', async () => {
    unsubscribeWithToken.mockResolvedValue({ message: 'done' });

    render(<UnsubscribeConfirm token="tok" />);
    fireEvent.click(screen.getByRole('button', { name: /turn off study reminders/i }));

    await waitFor(() => expect(screen.getByText(/study reminders are off/i)).toBeInTheDocument());
    expect(unsubscribeWithToken).toHaveBeenCalledWith('tok');
  });

  it('says which mail still arrives', async () => {
    // Someone who unsubscribes and then receives a receipt should not think it failed.
    unsubscribeWithToken.mockResolvedValue({ message: 'done' });

    render(<UnsubscribeConfirm token="tok" />);
    fireEvent.click(screen.getByRole('button', { name: /turn off study reminders/i }));

    await waitFor(() =>
      expect(screen.getByText(/diagnostic results and payment confirmations/i)).toBeInTheDocument(),
    );
  });

  it('offers a way through when the request fails', async () => {
    unsubscribeWithToken.mockRejectedValue(new ApiError(503, 'down'));

    render(<UnsubscribeConfirm token="tok" />);
    fireEvent.click(screen.getByRole('button', { name: /turn off study reminders/i }));

    await waitFor(() =>
      expect(screen.getByText(/could not update your preference/i)).toBeInTheDocument(),
    );
    expect(screen.getByRole('button', { name: /turn off study reminders/i })).toBeEnabled();
  });

  it('lets the reader keep them on', () => {
    render(<UnsubscribeConfirm token="tok" />);

    expect(screen.getByRole('link', { name: /keep them on/i })).toBeInTheDocument();
  });
});

describe('EmailPreferences', () => {
  it('shows the current state of each switch', () => {
    render(<EmailPreferences initial={preferences()} />);

    expect(screen.getByRole('button', { name: 'On' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Off' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('saves a switch immediately rather than waiting for a save button', async () => {
    // A save button would let someone turn reminders off, leave, and stay subscribed.
    setEmailPreferences.mockResolvedValue(preferences({ study_reminder_emails: false }));

    render(<EmailPreferences initial={preferences()} />);
    fireEvent.click(screen.getByRole('button', { name: 'On' }));

    await waitFor(() =>
      expect(setEmailPreferences).toHaveBeenCalledWith({
        study_reminder_emails: false,
        marketing_emails_opt_in: false,
      }),
    );
    expect(screen.queryByRole('button', { name: /save/i })).not.toBeInTheDocument();
  });

  it('renders the server state, not the optimistic one', async () => {
    // The API is what decides. Rendering the click would let the page disagree with what is
    // actually stored.
    setEmailPreferences.mockResolvedValue(preferences({ study_reminder_emails: true }));

    render(<EmailPreferences initial={preferences()} />);
    fireEvent.click(screen.getByRole('button', { name: 'On' }));

    await waitFor(() => expect(setEmailPreferences).toHaveBeenCalled());
    expect(screen.getByRole('button', { name: 'On' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('reports a failure without changing the displayed state', async () => {
    setEmailPreferences.mockRejectedValue(new ApiError(500, 'boom'));

    render(<EmailPreferences initial={preferences()} />);
    fireEvent.click(screen.getByRole('button', { name: 'On' }));

    await waitFor(() =>
      expect(screen.getByText(/could not update your preference/i)).toBeInTheDocument(),
    );
    expect(screen.getByRole('button', { name: 'On' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('names the mail that cannot be turned off', () => {
    render(<EmailPreferences initial={preferences()} />);

    expect(
      screen.getByText(/diagnostic results and payment confirmations are always sent/i),
    ).toBeInTheDocument();
  });
});
