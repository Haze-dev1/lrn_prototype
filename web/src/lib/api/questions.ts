/** Typed API client functions for the public question taxonomy. */

import { apiRequest } from '@/lib/api/client';

export interface Category {
  slug: string;
  name: string;
  description: string | null;
  display_order: number;
}

/**
 * Fetch the skill categories.
 *
 * Reference data that changes only by migration, so it is cached rather than refetched on every
 * render of every page that labels a category.
 */
export async function fetchCategories(): Promise<Category[]> {
  return apiRequest<Category[]>('/v1/categories', { next: { revalidate: 3600 } });
}
