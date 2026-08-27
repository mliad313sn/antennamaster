/**
 * Every backend call must carry the account's token.
 *
 * `authHeaders` lived in `saas.ts`, which imports `apiFetch` from `api.ts` —
 * so `api.ts` could not read it back without a circular import, and none of
 * the planner's own calls sent it. That accident had two costs, both measured
 * against the running stack:
 *
 *   * Click-to-inspect answered 404. `/api/rf/coverage/{id}/at` is
 *     owner-scoped, and the request arrived anonymous, so a signed-in user
 *     clicking their own coverage to read the level got nothing.
 *
 *   * The synchronous coverage fallback stored its result with NO OWNER.
 *     POST /api/rf/coverage without the header, then GET the raster as a
 *     total stranger → 200. A study a signed-in user ran that way — the path
 *     taken whenever the async job API refuses, e.g. under the rate limiter —
 *     left their georeferenced site footprint readable by anyone holding the
 *     12-hex id. That is exactly the leak the owner-scoping exists to
 *     prevent, arriving through the back door rather than the front.
 *
 * The token is safe to attach unconditionally here because every target is a
 * same-origin `/api/...` path; there is nowhere for it to leak to.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { apiFetch } from '@/lib/api';

const TOKEN = 'tok-xyz789';

beforeEach(() => localStorage.setItem('am_token', TOKEN));
afterEach(() => { localStorage.clear(); vi.restoreAllMocks(); });

describe('apiFetch', () => {
  it('attaches the bearer token', async () => {
    const f = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal('fetch', f);
    await apiFetch('/api/rf/coverage/abc/at?lat=47&lon=15');
    expect(f.mock.calls[0][1].headers).toMatchObject({
      Authorization: `Bearer ${TOKEN}`,
    });
  });

  it('attaches it to writes too, so the result is stored owned', async () => {
    // The leak was here: an unauthenticated POST produced an ownerless
    // result that anyone with the id could then read.
    const f = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal('fetch', f);
    await apiFetch('/api/rf/coverage', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    expect(f.mock.calls[0][1].headers).toMatchObject({
      Authorization: `Bearer ${TOKEN}`,
      'Content-Type': 'application/json',
    });
  });

  it('lets a caller override the header deliberately', async () => {
    const f = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal('fetch', f);
    await apiFetch('/api/x', { headers: { Authorization: 'Bearer other' } });
    expect(f.mock.calls[0][1].headers.Authorization).toBe('Bearer other');
  });

  it('sends nothing when anonymous, so self-hosting still works', async () => {
    localStorage.clear();
    const f = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal('fetch', f);
    await apiFetch('/api/rf/technologies');
    expect(f.mock.calls[0][1].headers.Authorization).toBeUndefined();
  });

  it('still aborts on timeout with the header in place', async () => {
    // The header must not have displaced the abort signal.
    const f = vi.fn().mockImplementation((_u: string, init: { signal: AbortSignal }) =>
      new Promise((_res, rej) => {
        init.signal.addEventListener('abort',
          () => rej(new DOMException('aborted', 'AbortError')));
      }));
    vi.stubGlobal('fetch', f);
    await expect(apiFetch('/api/slow', {}, 20)).rejects.toThrow(/took longer/);
  });
});
