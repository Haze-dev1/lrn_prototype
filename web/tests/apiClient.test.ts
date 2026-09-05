import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, apiRequest } from '@/lib/api/client';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

/** Build a fetch stub returning a single canned response. */
function stubFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('apiRequest', () => {
  it('returns the parsed body on success', async () => {
    stubFetch(Response.json({ status: 'healthy' }));

    await expect(apiRequest('/health/ready')).resolves.toEqual({ status: 'healthy' });
  });

  it('sends credentials so the session cookie travels with the request', async () => {
    const fetchMock = stubFetch(Response.json({}));

    await apiRequest('/profile');

    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ credentials: 'include' });
  });

  it('raises ApiError carrying the status for a non-2xx response', async () => {
    stubFetch(Response.json({ detail: 'Not found' }, { status: 404 }));

    await expect(apiRequest('/questions/missing')).rejects.toMatchObject({
      name: 'ApiError',
      status: 404,
      message: 'Not found',
    });
  });

  it('does not surface raw internals when the error body is not JSON', async () => {
    stubFetch(new Response('<html>gateway error</html>', { status: 502, statusText: 'Bad Gateway' }));

    await expect(apiRequest('/health/ready')).rejects.toMatchObject({
      status: 502,
      message: 'Bad Gateway',
    });
  });

  it('normalises a transport failure into a reachability error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network down')));

    const error = await apiRequest('/health/ready').catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(503);
    expect((error as ApiError).message).toBe('Could not reach the server.');
  });

  it('returns undefined for a 204 rather than attempting to parse an empty body', async () => {
    stubFetch(new Response(null, { status: 204 }));

    await expect(apiRequest('/sessions/abc')).resolves.toBeUndefined();
  });
});
