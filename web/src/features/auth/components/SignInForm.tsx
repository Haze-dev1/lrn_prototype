'use client';

import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { Input } from '@/components/ui/Input';
import { ApiError } from '@/lib/api/client';
import { login } from '@/lib/api/auth';
import { destinationAfterSignIn } from '@/lib/auth/redirect';

export interface SignInFormProps {
  /** Where to send the user after signing in, when they were redirected here from a gated page. */
  nextPath?: string;
}

/** Email and password sign-in form. */
export function SignInForm({ nextPath }: SignInFormProps) {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    setSubmitting(true);

    try {
      const user = await login(email, password);
      // Shared with Google sign-in, so only same-origin paths are ever honoured and one method
      // cannot be hardened while the other quietly is not.
      router.replace(destinationAfterSignIn(user.onboarding_complete, nextPath));
      router.refresh();
    } catch (error) {
      if (error instanceof ApiError && error.status === 429) {
        setFormError('Too many sign-in attempts. Please wait a few minutes and try again.');
      } else if (error instanceof ApiError && error.status === 403) {
        setFormError('This account is not active. Contact support if you think that is wrong.');
      } else {
        // One message for both "no such account" and "wrong password", matching the API.
        setFormError('Incorrect email or password.');
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

      <Field id="password" label="Password">
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          disabled={submitting}
        />
      </Field>

      <Button type="submit" size="lg" loading={submitting} fullWidth>
        {submitting ? 'Signing in' : 'Sign in'}
      </Button>
    </form>
  );
}
