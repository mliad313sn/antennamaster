/**
 * Nothing may hang forever.
 *
 * Every call in the API client was a bare `fetch`, which has no timeout. On
 * the hardware this is used on — a tablet that walks out of coverage
 * mid-study — the promise simply never settles: the UI sits on "Simulating…"
 * with no result, no error, and no way back except a reload. A request that
 * cannot finish has to fail, and say something the person holding the tablet
 * can act on.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { API_TIMEOUT_MS, HEAVY_TIMEOUT_MS, apiFetch } from '@/lib/api';

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

/** A fetch that never settles unless its signal aborts — the dropped
 *  connection this exists for. */
function hangingFetch() {
  return vi.fn((_url: string, init: RequestInit = {}) => new Promise<Response>(
    (_resolve, reject) => {
      init.signal?.addEventListener('abort', () => {
        const err = new Error('aborted');
        err.name = 'AbortError';
        reject(err);
      });
    }));
}

describe('apiFetch', () => {
  it('gives up instead of hanging, and says what to do about it', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', hangingFetch());

    const p: Promise<Error> = apiFetch('/api/rf/coverage', {}, 1000)
      .then(() => { throw new Error('expected a timeout'); }, (e) => e as Error);
    await vi.advanceTimersByTimeAsync(1100);
    const err = await p;

    expect(err.message).toMatch(/took longer than 1s/);
    // The message has to be actionable, not "AbortError".
    expect(err.message).toMatch(/try again|reduce the radius/i);
    expect(err.name).not.toBe('AbortError');
  });

  it('does not fire on a request that answers in time', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn(async () => new Response('ok')));
    const r = await apiFetch('/api/rf/technologies', {}, 5000);
    expect(await r.text()).toBe('ok');
    // No pending timer left behind to abort a later, unrelated request.
    expect(vi.getTimerCount()).toBe(0);
  });

  it("reports a dropped connection as one, not as 'Failed to fetch'", async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }));
    await expect(apiFetch('/api/rf/technologies'))
      .rejects.toThrow(/Could not reach the server/);
  });

  it("passes a caller's own cancel through instead of calling it a timeout", async () => {
    // A deliberate stop and a timeout are different events; turning one into
    // the other would show an error for something the user just asked for.
    vi.stubGlobal('fetch', hangingFetch());
    const ctl = new AbortController();
    const p = apiFetch('/api/rf/coverage', { signal: ctl.signal }, 60_000);
    ctl.abort();
    await expect(p).rejects.toThrow(/aborted/);
  });

  it('gives heavy work a much longer budget than a preset list', () => {
    // A full-resolution sweep is tens of seconds of compute; 30s would abort
    // studies that were about to succeed.
    expect(HEAVY_TIMEOUT_MS).toBeGreaterThan(API_TIMEOUT_MS * 3);
  });
});
