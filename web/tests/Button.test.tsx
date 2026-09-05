import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { Button } from '@/components/ui/Button';

describe('Button', () => {
  it('renders its label and is interactive by default', () => {
    render(<Button>Start session</Button>);

    const button = screen.getByRole('button', { name: 'Start session' });
    expect(button).toBeEnabled();
    expect(button).toHaveAttribute('aria-busy', 'false');
  });

  it('blocks interaction and reports busy state while loading', () => {
    const onClick = vi.fn();
    render(
      <Button loading onClick={onClick}>
        Submitting
      </Button>,
    );

    const button = screen.getByRole('button', { name: 'Submitting' });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-busy', 'true');
    button.click();
    expect(onClick).not.toHaveBeenCalled();
  });

  it('stays disabled when explicitly disabled', () => {
    render(<Button disabled>Locked</Button>);

    expect(screen.getByRole('button', { name: 'Locked' })).toBeDisabled();
  });
});
