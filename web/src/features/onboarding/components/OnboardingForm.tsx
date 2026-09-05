'use client';

import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { completeOnboarding, type Profile, type TargetRole } from '@/lib/api/auth';
import { ApiError } from '@/lib/api/client';

const ROLE_OPTIONS: { value: TargetRole; label: string }[] = [
  { value: 'ib', label: 'Investment banking' },
  { value: 'pe', label: 'Private equity' },
  { value: 'both', label: 'Both' },
];

/** Graduation years worth offering: this year through six years out covers current students. */
function graduationYears(): number[] {
  const start = new Date().getFullYear();
  return Array.from({ length: 7 }, (_, index) => start + index);
}

export interface OnboardingFormProps {
  profile: Profile | null;
}

/**
 * Three-question onboarding.
 *
 * Deliberately short: the diagnostic itself does the product education, and a long form before
 * any value has been shown is where people leave.
 */
export function OnboardingForm({ profile }: OnboardingFormProps) {
  const router = useRouter();
  const [school, setSchool] = useState(profile?.school ?? '');
  const [graduationYear, setGraduationYear] = useState(
    profile?.graduation_year ? String(profile.graduation_year) : '',
  );
  const [targetRole, setTargetRole] = useState<string>(profile?.target_role ?? '');
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const complete = school.trim() !== '' && graduationYear !== '' && targetRole !== '';

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    setSubmitting(true);

    try {
      await completeOnboarding({
        school: school.trim(),
        graduation_year: Number(graduationYear),
        target_role: targetRole as TargetRole,
      });
      router.replace('/dashboard');
      router.refresh();
    } catch (error) {
      setFormError(
        error instanceof ApiError && error.status === 422
          ? 'Please check your answers and try again.'
          : 'We could not save your details. Please try again.',
      );
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5" noValidate>
      {formError ? <Alert tone="error">{formError}</Alert> : null}

      <Field id="school" label="School">
        <Input
          id="school"
          name="school"
          required
          maxLength={200}
          value={school}
          onChange={(event) => setSchool(event.target.value)}
          disabled={submitting}
          placeholder="Where you study"
        />
      </Field>

      <Field id="graduation-year" label="Graduation year">
        <Select
          id="graduation-year"
          name="graduation_year"
          required
          value={graduationYear}
          onChange={(event) => setGraduationYear(event.target.value)}
          disabled={submitting}
        >
          <option value="" disabled>
            Select a year
          </option>
          {graduationYears().map((year) => (
            <option key={year} value={year}>
              {year}
            </option>
          ))}
        </Select>
      </Field>

      <Field
        id="target-role"
        label="What are you recruiting for?"
        hint="This shapes which questions you see."
      >
        <Select
          id="target-role"
          name="target_role"
          required
          value={targetRole}
          onChange={(event) => setTargetRole(event.target.value)}
          disabled={submitting}
        >
          <option value="" disabled>
            Select a track
          </option>
          {ROLE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
      </Field>

      <Button type="submit" size="lg" loading={submitting} disabled={!complete} fullWidth>
        {submitting ? 'Saving' : 'Continue'}
      </Button>
    </form>
  );
}
