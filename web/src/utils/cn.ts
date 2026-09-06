/**
 * Merge class names, resolving Tailwind conflicts so the last value wins.
 *
 * Framework-neutral on purpose: this module carries no `'use client'` directive, so Server and
 * Client Components can both call it. A `'use client'` module's non-component exports are client
 * reference proxies in the RSC graph and throw when invoked during a server render.
 */

import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
