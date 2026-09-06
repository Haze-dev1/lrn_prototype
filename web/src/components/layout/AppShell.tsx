import Link from 'next/link';
import type { Route } from 'next';
import type { ReactNode } from 'react';
import { SignOutButton } from '@/features/auth/components/SignOutButton';
import { ThemeToggle } from './ThemeToggle';
import { cn } from '@/utils/cn';

interface NavItem {
  href: Route;
  label: string;
}

const NAV_ITEMS: NavItem[] = [
  { href: '/practice', label: 'Practice' },
  { href: '/dashboard', label: 'Dashboard' },
  { href: '/review', label: 'Review' },
  { href: '/progress', label: 'Progress' },
  { href: '/diagnostic', label: 'Diagnostic' },
  { href: '/glossary', label: 'Glossary' },
];

const ADMIN_NAV_ITEM: NavItem = { href: '/admin/questions', label: 'Question Bank' };

export interface AppShellProps {
  email: string;
  current: string;
  isAdmin?: boolean;
  children: ReactNode;
}

export function AppShell({ email, current, isAdmin = false, children }: AppShellProps) {
  const navItems = isAdmin ? [...NAV_ITEMS, ADMIN_NAV_ITEM] : NAV_ITEMS;

  return (
    <div className="flex min-h-dvh flex-col bg-canvas text-text-primary">
      {/* Keyboard users would otherwise tab through seven nav pills and the theme toggle on
          every page before reaching the content. */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:border focus:border-border-strong focus:bg-surface-elevated focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-text-primary focus:outline-none focus:ring-2 focus:ring-accent"
      >
        Skip to content
      </a>

      {/* Top Navbar */}
      <header className="sticky top-0 z-40 border-b border-border-subtle bg-surface-1/80 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
          
          <div className="flex items-center gap-8">
            <Link href="/dashboard" className="label-micro text-text-primary hover:text-accent transition-colors">
              LRN
            </Link>
            
            {/* Desktop Navigation */}
            <nav aria-label="Main" className="hidden md:block">
              <ul className="flex items-center gap-1">
                {navItems.map((item) => {
                  const active = current === item.href;
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        aria-current={active ? 'page' : undefined}
                        className={cn(
                          'block rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                          active
                            ? 'bg-accent/10 text-accent font-semibold'
                            : 'text-text-secondary hover:bg-surface-2 hover:text-text-primary'
                        )}
                      >
                        {item.label}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </nav>
          </div>

          <div className="flex items-center gap-3">
            <ThemeToggle />
            {/* Sign out lives in the always-visible header row, not the mobile pill strip:
                behind horizontal scroll it was reachable but invisible. */}
            <div className="flex items-center gap-3 border-l border-border-subtle pl-3">
              <span
                className="hidden max-w-[150px] truncate text-xs text-text-muted md:inline"
                title={email}
              >
                {email}
              </span>
              <SignOutButton />
            </div>
          </div>
        </div>

        {/* Mobile Navigation (Scrollable horizontally) */}
        <nav
          aria-label="Mobile Main"
          className="border-t border-border-subtle md:hidden overflow-x-auto px-4 py-2"
        >
          <ul className="flex w-max items-center gap-2">
            {navItems.map((item) => {
              const active = current === item.href;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? 'page' : undefined}
                    className={cn(
                      'block rounded-full px-4 py-1.5 text-sm font-medium transition-colors',
                      active
                        ? 'bg-accent text-accent-foreground'
                        : 'bg-surface-2 text-text-secondary hover:bg-surface-3 hover:text-text-primary'
                    )}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </header>

      {/* Main content area. Deliberately a div: every page rendering this shell owns its own
          <main>, and a document may only have one main landmark. */}
      <div id="main-content" className="flex-1 flex flex-col">
        {children}
      </div>
    </div>
  );
}
