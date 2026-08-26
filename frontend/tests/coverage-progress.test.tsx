/**
 * The planner's coverage study runs as a queued job with live progress.
 *
 * A full-resolution sweep (720 radials x 400 steps) was measured at ~26 s of
 * compute. Run synchronously that is a blocking request with no feedback that
 * a reverse proxy may time out, and the sixth concurrent study is refused with
 * a 429 whose body tells the user to call an HTTP endpoint. These tests pin
 * the queued behaviour and the error humanising that replaced it.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

import { CoverageCancelled, friendlyError, simulateCoverageTracked } from '@/lib/api';

describe('friendlyError', () => {
  it('rewrites the busy-worker 429 into advice a planner can act on', () => {
    // Verbatim body returned by the live backend when all 6 slots are taken.
    const raw = '6 simulations already running on this worker - retry shortly '
      + 'or use POST /api/saas/coverage/async';
    const out = friendlyError(raw);
    expect(out).not.toContain('/api/saas');   // no API instructions in a GUI
    expect(out).not.toContain('POST');
    expect(out).toMatch(/busy/i);
    expect(out).toMatch(/again/i);            // tells them what to do next
  });

  it('explains a timeout in terms of the knobs the user controls', () => {
    expect(friendlyError('Request timed out')).toMatch(/radius|radials|steps/i);
  });

  it('passes unrecognised errors through untouched, never masking a real one', () => {
    const real = 'Selected layers contain fewer than 3 elevation points';
    expect(friendlyError(real)).toBe(real);
  });
});

describe('simulateCoverageTracked', () => {
  const params = {
    lat: 47, lon: 15, technology: 'gsm900', radiusKm: 8, dxfId: null,
  };

  beforeEach(() => { vi.restoreAllMocks(); });
  afterEach(() => { vi.unstubAllGlobals(); });

  it('queues the job, reports progress 0..1, and returns the result', async () => {
    const polls = [
      { id: 'j1', status: 'queued', progress: 0, result: null, error: null },
      { id: 'j1', status: 'running', progress: 0.5, result: null, error: null },
      { id: 'j1', status: 'done', progress: 1, result: { coverage_id: 'c1' }, error: null },
    ];
    let poll = 0;
    vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
      ok: true, status: 200,
      json: async () => (String(url).includes('/coverage/async')
        ? { job_id: 'j1' }
        : polls[Math.min(poll++, polls.length - 1)]),
    })) as unknown as typeof fetch);

    const seen: number[] = [];
    const res = await simulateCoverageTracked(params, (p) => seen.push(p));

    expect((res as unknown as { coverage_id: string }).coverage_id).toBe('c1');
    expect(seen[0]).toBe(0);                       // starts at zero
    expect(seen[seen.length - 1]).toBe(1);         // ends complete
    expect(seen).toContain(0.5);                   // and reports the middle
  });

  it('surfaces a failed job with its reason rather than hanging', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
      ok: true, status: 200,
      json: async () => (String(url).includes('/coverage/async')
        ? { job_id: 'j2' }
        : { id: 'j2', status: 'failed', progress: 1, result: null,
            error: 'DEM tile unavailable' }),
    })) as unknown as typeof fetch);

    await expect(simulateCoverageTracked(params, () => {}))
      .rejects.toThrow(/DEM tile unavailable/);
  });

  it('reports a user cancellation distinctly, not as a failure', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
      ok: true, status: 200,
      json: async () => (String(url).includes('/coverage/async')
        ? { job_id: 'j3' }
        : { id: 'j3', status: 'cancelled', progress: 1, result: null, error: null }),
    })) as unknown as typeof fetch);

    // Stopping your own study must be distinguishable so the UI can stay
    // quiet instead of showing a scary error box.
    await expect(simulateCoverageTracked(params, () => {}))
      .rejects.toBeInstanceOf(CoverageCancelled);
  });

  it('hands the caller a cancel handle once the job is queued', async () => {
    const calls: { url: string; method?: string }[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url: String(url), method: init?.method });
      return {
        ok: true, status: 200,
        json: async () => (String(url).includes('/coverage/async')
          ? { job_id: 'j4' }
          : { id: 'j4', status: 'cancelled', progress: 0.3, result: null, error: null }),
      };
    }) as unknown as typeof fetch);

    let cancel: (() => void) | null = null;
    await expect(simulateCoverageTracked(params, () => {}, (c) => { cancel = c; }))
      .rejects.toBeInstanceOf(CoverageCancelled);
    expect(cancel).toBeTypeOf('function');
    cancel!();
    await Promise.resolve();
    expect(calls.some((c) => c.method === 'DELETE' && c.url.includes('/jobs/j4')))
      .toBe(true);
  });

  it('falls back to the synchronous endpoint when the job API is absent', async () => {
    // An older backend 404s /coverage/async; the button must still work.
    const calls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      calls.push(String(url));
      if (String(url).includes('/coverage/async')) {
        return { ok: false, status: 404, statusText: 'Not Found',
                 json: async () => ({ detail: 'Not Found' }) };
      }
      return { ok: true, status: 200, json: async () => ({ coverage_id: 'sync1' }) };
    }) as unknown as typeof fetch);

    const res = await simulateCoverageTracked(params, () => {});
    expect((res as unknown as { coverage_id: string }).coverage_id).toBe('sync1');
    expect(calls.some((u) => u.includes('/api/rf/coverage'))).toBe(true);
  });
});
