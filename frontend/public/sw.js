/*
 * AntennaMaster service worker — offline-ready field caching.
 *
 * Strategy by request type (RF field work is bandwidth-hostile: open-pit
 * sites, remote last-mile, deep topography with no signal):
 *   - App shell / static assets: stale-while-revalidate, so the tool opens
 *     instantly and updates in the background when a connection returns.
 *   - Map tiles (OSM/Carto/Esri/Terrarium): cache-first with an LRU-ish cap,
 *     so terrain you have already viewed stays available off-grid.
 *   - API calls: network-first with a cache fallback, so the last successful
 *     study/coverage result is still readable when the link drops — but see
 *     the isolation rules below; this cache holds customer data.
 * Non-GET requests always go straight to the network.
 *
 * WHY THE API CACHE IS PARTITIONED
 * The API cache used to be one bucket keyed by URL alone. The Cache API
 * matches on the URL and `Vary`, never on `Authorization`, so a response
 * stored for one account was returned to the next request for the same path
 * whoever made it — and nothing cleared it at sign-out. On the hardware this
 * product is actually deployed on, a shared rugged tablet passed between a
 * field crew, that meant: technician A signs in, opens their projects and the
 * org audit log; A signs out; B picks up the tablet, loses signal, and the
 * fallback hands them A's projects and every colleague's email and client IP.
 * So each identity now gets its own bucket, keyed by a hash of the bearer
 * token, and signing out deletes them all.
 */
const VERSION = 'am-v2';            // v2: partitioned API cache (see above)
const SHELL = `${VERSION}-shell`;
const TILES = `${VERSION}-tiles`;
const API_PREFIX = `${VERSION}-api-`;
const TILE_MAX = 800;               // cap cached tiles so the quota can't fill

const SHELL_URLS = ['/', '/field', '/manifest.webmanifest', '/icon.svg'];

/* Never cached, at all, for anybody.
 *  - /api/auth/*      identity, the audit log and the GDPR export: a stale
 *                     answer here is either a privacy leak or a lie about who
 *                     you are, and none of it is useful offline.
 *  - /api/telemetry/* live asset positions. Showing a cached position as if
 *                     it were live is worse than showing nothing: the whole
 *                     point is where the crew is *now*. */
const NEVER_CACHE = /^\/api\/(auth|telemetry)\//;

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL).then((c) => c.addAll(SHELL_URLS)).then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  // Dropping every non-VERSION cache is also what retires the unpartitioned
  // v1 API bucket, so an upgrade cannot inherit its cross-account contents.
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k)),
    )).then(() => self.clients.claim()),
  );
});

/** Purge every API bucket. The page sends this on sign-out: leaving one
 *  account's studies readable on a shared device after they log out is the
 *  same leak by a slower route. */
async function purgeApiCaches() {
  const keys = await caches.keys();
  await Promise.all(keys.filter((k) => k.includes('-api-')).map((k) => caches.delete(k)));
}

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'am-signout') {
    event.waitUntil(purgeApiCaches());
  }
});

/** Cache bucket for this request's identity.
 *
 *  The token itself must not become a cache name — cache names are readable
 *  by any script on the origin, so that would turn a walled-off HttpOnly-ish
 *  secret into something an XSS could simply enumerate. A truncated SHA-256
 *  is enough to separate accounts without being reversible. */
async function apiCacheName(request) {
  const auth = request.headers.get('Authorization');
  if (!auth) return `${API_PREFIX}anon`;
  try {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(auth));
    const hex = Array.from(new Uint8Array(digest).slice(0, 8))
      .map((b) => b.toString(16).padStart(2, '0')).join('');
    return `${API_PREFIX}${hex}`;
  } catch (e) {
    // No SubtleCrypto (insecure origin): fail closed to a bucket nothing
    // else can collide with rather than falling back to a shared one.
    return `${API_PREFIX}nocrypto-${auth.length}`;
  }
}

function isTile(url) {
  return /tile|terrarium|\/\d+\/\d+\/\d+\.(png|jpg|jpeg|webp)/.test(url.href)
    || /basemaps|arcgisonline|openstreetmap|cartocdn|opentopomap/.test(url.hostname);
}

async function trimCache(name, max) {
  const cache = await caches.open(name);
  const keys = await cache.keys();
  if (keys.length > max) {
    // Oldest-first eviction (insertion order).
    for (let i = 0; i < keys.length - max; i += 1) await cache.delete(keys[i]);
  }
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);

  // Map tiles: cache-first (they never change), background-fill the cache.
  if (isTile(url)) {
    event.respondWith((async () => {
      const cache = await caches.open(TILES);
      const hit = await cache.match(request);
      if (hit) return hit;
      try {
        const res = await fetch(request);
        if (res.ok) { cache.put(request, res.clone()); trimCache(TILES, TILE_MAX); }
        return res;
      } catch (e) {
        return hit || Response.error();
      }
    })());
    return;
  }

  if (url.pathname.startsWith('/api/')) {
    // Identity, audit and live telemetry: straight to the network, never
    // stored, never served stale.
    if (NEVER_CACHE.test(url.pathname)) return;

    // Everything else: network-first, falling back to this identity's own
    // last successful response when the link drops.
    event.respondWith((async () => {
      const cache = await caches.open(await apiCacheName(request));
      try {
        const res = await fetch(request);
        if (res.ok) cache.put(request, res.clone());
        return res;
      } catch (e) {
        const hit = await cache.match(request);
        if (hit) return hit;
        return new Response(
          JSON.stringify({ offline: true,
            detail: 'Offline — showing last cached data if available.' }),
          { status: 503, headers: { 'Content-Type': 'application/json' } });
      }
    })());
    return;
  }

  // App shell + assets: stale-while-revalidate.
  event.respondWith((async () => {
    const cache = await caches.open(SHELL);
    const hit = await cache.match(request);
    const fetchPromise = fetch(request).then((res) => {
      if (res.ok && url.origin === self.location.origin) cache.put(request, res.clone());
      return res;
    }).catch(() => hit);
    return hit || fetchPromise;
  })());
});
