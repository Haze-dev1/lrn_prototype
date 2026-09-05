'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { Button } from '@/components/ui/Button';
import { logout } from '@/lib/api/auth';

/** Ends the session and returns to the public site. */
export function SignOutButton() {
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await logout();
    } catch {
      // The API always clears cookies and reports success; even if the call failed outright,
      // sending the user to the public site is the right outcome for them.
    }
    router.replace('/');
    router.refresh();
  }

  return (
    <Button variant="ghost" size="sm" loading={signingOut} onClick={handleSignOut}>
      Sign out
    </Button>
  );
}
