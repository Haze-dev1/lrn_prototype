/**
 * The API client must carry a structured error `detail` through unflattened.
 *
 * Rubric validation answers 422 with the full list of what is wrong. Collapsing that into one
 * sentence would leave a content author unable to see what to fix, so the shape is pinned here.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, apiRequest } from '@/lib/api/client';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function stubFetch(response: Response) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response));
}

describe('structured error details', () => {
  it('carries a validation detail object through to the caller', async () => {
    stubFetch(
      Response.json(
        {
          detail: {
            message: 'This version is not complete enough to publish.',
            is_valid: false,
            errors: ['Ideal answer is required.', 'At least one expected concept is required.'],
            warnings: [],
          },
        },
        { status: 422 },
      ),
    );

    const caught = await apiRequest('/v1/admin/questions/x/versions').catch(
      (error: unknown) => error,
    );

    expect(caught).toBeInstanceOf(ApiError);
    const error = caught as ApiError;
    expect(error.status).toBe(422);
    expect(error.message).toBe('This version is not complete enough to publish.');
    expect((error.detail as { errors: string[] }).errors).toHaveLength(2);
  });

  it('still uses a string detail as the message', async () => {
    stubFetch(Response.json({ detail: 'Question not found' }, { status: 404 }));

    await expect(apiRequest('/v1/admin/questions/x')).rejects.toMatchObject({
      status: 404,
      message: 'Question not found',
      detail: 'Question not found',
    });
  });

  it('falls back to status text when the detail has no message field', async () => {
    stubFetch(
      Response.json({ detail: { errors: ['something'] } }, { status: 422, statusText: 'Unprocessable Content' }),
    );

    const caught = (await apiRequest('/v1/admin/questions').catch(
      (error: unknown) => error,
    )) as ApiError;

    expect(caught.message).toBe('Unprocessable Content');
    expect(caught.detail).toEqual({ errors: ['something'] });
  });

  it('leaves detail undefined when the body is not JSON', async () => {
    stubFetch(new Response('<html>gateway</html>', { status: 502, statusText: 'Bad Gateway' }));

    const caught = (await apiRequest('/v1/categories').catch((error: unknown) => error)) as ApiError;

    expect(caught.detail).toBeUndefined();
    expect(caught.message).toBe('Bad Gateway');
  });
});
