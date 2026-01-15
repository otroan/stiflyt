/**
 * Tests for API client helpers
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { isAbortError, requestWithAbort } from '../client';

describe('api client helpers', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('should detect AbortError DOMException', () => {
    const error = new DOMException('The operation was aborted.', 'AbortError');
    expect(isAbortError(error)).toBe(true);
  });

  it('should detect error objects with name AbortError', () => {
    const error = { name: 'AbortError' };
    expect(isAbortError(error)).toBe(true);
  });

  it('should return false for non-abort errors', () => {
    expect(isAbortError(new Error('Boom'))).toBe(false);
    expect(isAbortError({ name: 'OtherError' })).toBe(false);
    expect(isAbortError(null)).toBe(false);
    expect(isAbortError('AbortError')).toBe(false);
  });
});

describe('requestWithAbort retry logic', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    localStorage.setItem('user', 'test-user');
  });

  afterEach(() => {
    localStorage.removeItem('user');
    vi.useRealTimers();
  });

  it('retries on retryable server error and succeeds', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: 'Server Error',
        json: async () => ({ detail: 'Server Error' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true }),
      });

    global.fetch = fetchMock as unknown as typeof fetch;

    const promise = requestWithAbort('/v1/routes/test', { retries: 1, retryDelay: 1 });
    await vi.runAllTimersAsync();
    const result = await promise;

    expect(result).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('does not retry on 400 errors', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 400,
      statusText: 'Bad Request',
      json: async () => ({ detail: 'Bad Request' }),
    });

    global.fetch = fetchMock as unknown as typeof fetch;

    await expect(requestWithAbort('/v1/routes/test', { retries: 1, retryDelay: 1 }))
      .rejects.toMatchObject({ statusCode: 400 });

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
