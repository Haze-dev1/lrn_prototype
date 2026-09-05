/** API client functions for service health. */

import { apiRequest } from '@/lib/api/client';

export interface DependencyHealth {
  name: string;
  healthy: boolean;
}

export interface HealthStatus {
  status: 'healthy' | 'degraded';
  service: string;
  dependencies: DependencyHealth[];
}

/**
 * Fetch aggregate backend readiness.
 *
 * Never cached: a cached health result would report a stale view of the system precisely when an
 * accurate one matters.
 */
export async function fetchReadiness(): Promise<HealthStatus> {
  return apiRequest<HealthStatus>('/health/ready', { cache: 'no-store' });
}
