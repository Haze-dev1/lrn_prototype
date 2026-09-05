'use client';

import { useRouter } from 'next/navigation';
import { useState, type FormEvent } from 'react';

import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { updateProfile, type Profile, type TargetRole } from '@/lib/api/auth';

const ROLE_OPTIONS: { value: TargetRole; label: string }[] = [
  { value: 'ib', label: 'Investment banking' },
  { value: 'pe', label: 'Private equity' },
  { value: 'both', label: 'Both' },
];

function graduationYears(): number[] {
  const start = new Date().getFullYear();
  return Array.from({ length: 7 }, (_, index) => start + index);
}

export interface ProfileFormProps {
  email: string;
  profile: Profile | null;
}

/** Editable profile details. Consent lives in its own control and is not editable here. */
export function ProfileForm({ email, profile }: ProfileFormProps) {
  const router = useRouter();
  const [school, setSchool] = useState(profile?.school ?? '');
  const [graduationYear, setGraduationYear] = useState(
    profile?.graduation_year ? String(profile.graduation_year) : '',
  );
  const [targetRole, setTargetRole] = useState<string>(profile?.target_role ?? '');
  const [status, setStatus] = useState<'idle' | 'saved' | 'error'>('idle');
  const [saving, setSaving] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus('idle');
    setSaving(true);
    try {
      await updateProfile({
        school: school.trim(),
        graduation_year: Number(graduationYear),
        target_role: targetRole as TargetRole,
      });
      setStatus('saved');
      router.refresh();
    } catch {
      setStatus('error');
    } finally {
      setSaving(false);
    }
  }

  return (
    <section
      aria-labelledby="profile-heading"
      className="rounded-[--radius-card] border border-border-subtle bg-surface-1 p-6"
    >
      <h2 id="profile-heading" className="label-micro">
        Profile
      </h2>

      <form onSubmit={handleSubmit} className="mt-4 space-y-5" noValidate>
        {status === 'saved' ? <Alert tone="success">Profile saved.</Alert> : null}
        {status === 'error' ? (
          <Alert tone="error">We could not save your profile. Please try again.</Alert>
        ) : null}

        <Field id="account-email" label="Email" hint="Contact support to change this.">
          <Input id="account-email" value={email} disabled readOnly />
        </Field>

        <Field id="profile-school" label="School">
          <Input
            id="profile-school"
            maxLength={200}
            value={school}
            onChange={(event) => setSchool(event.target.value)}
            disabled={saving}
          />
        </Field>

        <Field id="profile-year" label="Graduation year">
          <Select
            id="profile-year"
            value={graduationYear}
            onChange={(event) => setGraduationYear(event.target.value)}
            disabled={saving}
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

        <Field id="profile-role" label="Recruiting for">
          <Select
            id="profile-role"
            value={targetRole}
            onChange={(event) => setTargetRole(event.target.value)}
            disabled={saving}
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

        <Button type="submit" loading={saving} disabled={school.trim() === ''}>
          {saving ? 'Saving' : 'Save changes'}
        </Button>
      </form>
    </section>
  );
}
