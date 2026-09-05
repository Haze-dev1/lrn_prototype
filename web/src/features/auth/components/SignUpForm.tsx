'use client';

import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { describedBy, Field } from '@/components/ui/Field';
import { Input } from '@/components/ui/Input';
import { ApiError } from '@/lib/api/client';
import { register } from '@/lib/api/auth';

/** Mirrors the server's rule. Client validation is for feedback only; the API re-checks. */
const MIN_PASSWORD_LENGTH = 10;

/**
 * Account creation form.
 *
 * On success the browser already holds the session cookies the API set, so the user goes straight
 * to onboarding rather than being asked to sign in again.
 */
export function SignUpForm() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    setFieldError(null);

    if (password.length < MIN_PASSWORD_LENGTH) {
      setFieldError(`Use at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }

    setSubmitting(true);
    try {
      await register(email, password);
      // refresh() re-runs the server components so the new session is reflected everywhere.
      router.replace('/onboarding');
      router.refresh();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        // Deliberately does not confirm the address is registered — that would make sign-up an
        // account-enumeration oracle just as surely as a leaky login form.
        setFormError('That email address cannot be used. Try signing in instead.');
      } else if (error instanceof ApiError && error.status === 429) {
        setFormError('Too many attempts. Please wait a few minutes and try again.');
      } else {
        setFormError('We could not create your account. Please try again.');
      }
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5" noValidate>
      {formError ? <Alert tone="error">{formError}</Alert> : null}

      <Field id="email" label="Email">
        <Input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          disabled={submitting}
          placeholder="you@university.edu"
        />
      </Field>

      <Field
        id="password"
        label="Password"
        hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
        error={fieldError}
      >
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete="new-password"
          required
          minLength={MIN_PASSWORD_LENGTH}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          disabled={submitting}
          invalid={fieldError !== null}
          aria-describedby={describedBy('password', 'hint', fieldError)}
        />
      </Field>

      <Button type="submit" size="lg" loading={submitting} fullWidth>
        {submitting ? 'Creating your account' : 'Create account'}
      </Button>
    </form>
  );
}
