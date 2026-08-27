/**
 * Is the backend actually reachable?
 *
 * `navigator.onLine` answers a different question — whether a network
 * interface exists — and every browser vendor documents it that way. The two
 * come apart in exactly the situation the tactical view is built for: a
 * technician on a site LAN, on a hotspot with no upstream, or behind a captive
 * portal. Reproduced elsewhere in this app: `navigator.onLine === true` while
 * nothing could be fetched at all.
 *
 * On the tactical view that flag drove a badge reading "● Online" — on the
 * screen a technician checks *before they climb*, where believing you can
 * reach the terrain service and being wrong is the expensive mistake. So ask
 * the backend instead of asking the browser.
 *
 * `navigator.onLine === false` is still trusted in the negative direction:
 * when it does fire it is right, and it saves a doomed request.
 */
export const REACHABILITY_TIMEOUT_MS = 4000;

export async function probeBackend(
  fetchImpl: typeof fetch = fetch,
  timeoutMs = REACHABILITY_TIMEOUT_MS,
): Promise<boolean> {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) return false;
  const ctl = typeof AbortController !== 'undefined' ? new AbortController() : null;
  const timer = ctl ? setTimeout(() => ctl.abort(), timeoutMs) : null;
  try {
    // `ok`, not "any response". `/api/health` is liveness only and answers
    // 200 or nothing — so any other status did not come from a live backend.
    // Measured with the backend stopped: the web app's own proxy answers
    // **HTTP 500** rather than failing the request, so treating a response as
    // proof of reachability would report "Online" with the backend dead. That
    // is the same mistake as trusting `navigator.onLine`, one layer down.
    const r = await fetchImpl('/api/health',
      { cache: 'no-store', signal: ctl?.signal });
    return r.ok;
  } catch {
    return false;                 // network failure, timeout, or abort
  } finally {
    if (timer) clearTimeout(timer);
  }
}
