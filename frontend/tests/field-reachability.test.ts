/**
 * The tactical view's connectivity badge must reflect the backend, not
 * `navigator.onLine`.
 *
 * That flag reports whether a network interface exists, not whether anything
 * can be reached, and the two come apart in exactly the situation this screen
 * is for: a site LAN with no route out, a hotspot with no upstream, a captive
 * portal. Reproduced elsewhere in this app in the same session:
 * `navigator.onLine === true` while every request failed.
 *
 * The badge sat on the screen a technician checks *before they climb*. Telling
 * them the terrain service is reachable when it is not is the expensive
 * direction to be wrong in, which is why this is worth a probe rather than a
 * flag lookup.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

import { probeBackend } from '@/lib/reachability';

const onLine = (v: boolean) =>
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(v);

afterEach(() => vi.restoreAllMocks());

describe('backend reachability', () => {
  it('reports unreachable when the request fails, even though the browser says online', () => {
    onLine(true);
    const failing = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    return expect(probeBackend(failing as unknown as typeof fetch)).resolves.toBe(false);
  });

  it('reports reachable when the backend answers', async () => {
    onLine(true);
    const ok = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    await expect(probeBackend(ok as unknown as typeof fetch)).resolves.toBe(true);
    expect(ok).toHaveBeenCalledWith('/api/health', expect.objectContaining({ cache: 'no-store' }));
  });

  it('is not fooled by the proxy answering on a dead backend\'s behalf', async () => {
    // Measured with the backend stopped: `GET /api/health` through the web
    // app's own proxy returns **HTTP 500**, not a network failure. So "we got
    // a response" is not evidence of anything — treating it as such would put
    // "● Online" on the badge with nothing behind it, which is the very
    // mistake this replaced `navigator.onLine` to avoid.
    onLine(true);
    for (const status of [500, 502, 503, 504]) {
      const proxied = vi.fn().mockResolvedValue({ ok: false, status });
      await expect(probeBackend(proxied as unknown as typeof fetch),
        `status ${status}`).resolves.toBe(false);
    }
  });

  it('does not fire a doomed request when the browser knows it is offline', async () => {
    // `navigator.onLine === false` is still trusted: when it fires it is
    // right, and skipping the request saves a timeout on a screen someone is
    // holding in one hand up a mast.
    onLine(false);
    const spy = vi.fn();
    await expect(probeBackend(spy as unknown as typeof fetch)).resolves.toBe(false);
    expect(spy).not.toHaveBeenCalled();
  });

  it('gives up rather than hanging', async () => {
    onLine(true);
    // A request that never settles must not leave the badge stuck: the abort
    // rejects the promise, which is the unreachable answer.
    const hanging = vi.fn().mockImplementation((_url: string, init: { signal?: AbortSignal }) =>
      new Promise((_res, rej) => {
        init.signal?.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError')));
      }));
    await expect(probeBackend(hanging as unknown as typeof fetch, 20)).resolves.toBe(false);
  });
});
