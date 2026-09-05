/**
 * Signed-in application shell.
 *
 * A persistent sidebar on desktop and a compact bar on mobile. Navigation is deliberately short:
 * the product's job is to answer where you are and what to do next, and a wide nav invites
 * wandering instead.
 *
 * On mobile the nav row scrolls horizontally rather than wrapping. Six destinations — seven for
 * an administrator — do not fit across a phone, and a wrapping row pushes the page's actual
 * content below the fold before the reader has done anything.
 */

import Link from 'next/link';
import type { Route } from 'next';
import type { ReactNode } from 'react';

import { SignOutButton } from '@/features/auth/components/SignOutButton';

interface NavItem {
  href: Route;
  label: string;
}

const NAV_ITEMS: NavItem[] = [
  { href: '/dashboard', label: 'Home' },
  { href: '/practice', label: 'Practice' },
  { href: '/review', label: 'Review' },
  { href: '/progress', label: 'Progress' },
  { href: '/diagnostic', label: 'Diagnostic' },
  { href: '/account', label: 'Account' },
];

const ADMIN_NAV_ITEM: NavItem = { href: '/admin/questions', label: 'Question bank' };

export interface AppShellProps {
  email: string;
  current: string;
  /** Show the content administration link. Presentation only — the API gates the routes. */
  isAdmin?: boolean;
  children: ReactNode;
}

export function AppShell({ email, current, isAdmin = false, children }: AppShellProps) {
  const navItems = isAdmin ? [...NAV_ITEMS, ADMIN_NAV_ITEM] : NAV_ITEMS;
  return (
    <div className="flex min-h-dvh flex-col md:flex-row">
      <header className="border-b border-border-subtle bg-surface-1 md:w-56 md:shrink-0 md:border-r md:border-b-0">
        <div className="md:px-5 md:py-6">
          <div className="flex items-center justify-between gap-3 px-5 pt-4 pb-3 md:block md:p-0">
            <Link href="/dashboard" className="label-micro hover:text-text-secondary">
              LRN
            </Link>
            {/* Identity and sign-out live in the sidebar footer on desktop, which does not exist
                on mobile — so they sit here instead. Without this there is no way to sign out on
                a phone at all. */}
            <div className="flex items-center gap-3 md:hidden">
              <span className="max-w-[9rem] truncate text-xs text-text-muted" title={email}>
                {email}
              </span>
              <SignOutButton />
            </div>
          </div>

          {/* Seven destinations do not fit across 390px, and a wrapping row pushes the page
              content below the fold on a phone. The row scrolls instead: everything stays one
              tap away, and the overflow is horizontal rather than vertical.
              `-mx-5 px-5` lets the scroll region bleed to the screen edges so the first and last
              items are not clipped against the page gutter. */}
          <nav
            aria-label="Main"
            className="-mx-5 overflow-x-auto px-5 pb-3 md:mx-0 md:mt-8 md:overflow-visible md:px-0 md:pb-0"
          >
            <ul className="flex w-max items-center gap-1 md:w-auto md:flex-col md:items-stretch md:gap-0.5">
              {navItems.map((item) => {
                const active = current === item.href;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      aria-current={active ? 'page' : undefined}
                      className={[
                        'block rounded-md px-3 py-2 text-sm whitespace-nowrap transition-colors',
                        active
                          ? 'bg-surface-2 text-text-primary'
                          : 'text-text-secondary hover:bg-surface-2 hover:text-text-primary',
                      ].join(' ')}
                    >
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>
        </div>

        <div className="hidden border-t border-border-subtle px-5 py-4 md:block">
          <p className="truncate text-xs text-text-muted" title={email}>
            {email}
          </p>
          <div className="mt-2">
            <SignOutButton />
          </div>
        </div>
      </header>

      <div className="flex-1">{children}</div>
    </div>
  );
}
