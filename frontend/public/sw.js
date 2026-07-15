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
 *     study/coverage result is still readable when the link drops.
 * Non-GET requests always go straight to the network.
 */
const VERSION = 'am-v1';
const SHELL = `${VERSION}-shell`;
const TILES = `${VERSION}-tiles`;
const API = `${VERSION}-api`;
const TILE_MAX = 800;               // cap cached tiles so the quota can't fill

const SHELL_URLS = ['/', '/field', '/manifest.webmanifest', '/icon.svg'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL).then((c) => c.addAll(SHELL_URLS)).then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k)),
    )).then(() => self.clients.claim()),
  );
});

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

  // API: network-first, fall back to the last cached response when offline.
  if (url.pathname.startsWith('/api/')) {
    event.respondWith((async () => {
      const cache = await caches.open(API);
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
