/**
 * The offline cache must not hand one account's data to the next.
 *
 * This product is deployed on shared rugged tablets passed between a field
 * crew, and the PWA cache is what makes it useful there. The Cache API
 * matches on URL and `Vary` — never on `Authorization` — so a single API
 * bucket keyed by URL returns whatever was stored last, to whoever asks, and
 * nothing cleared it at sign-out. Technician A opens their projects and the
 * org audit log; A signs out; B picks up the tablet, loses signal, and the
 * offline fallback serves them A's studies and every colleague's email.
 *
 * The service worker is a classic worker script, so it is loaded here into a
 * harness with the same shapes the browser gives it. The cache mock
 * deliberately ignores request headers, exactly as the real Cache API does —
 * that is the behaviour under test, not a shortcut.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { beforeEach, describe, expect, it } from 'vitest';

const SRC = readFileSync(resolve(__dirname, '../public/sw.js'), 'utf8');

class FakeCache {
  map = new Map<string, Response>();
  async match(req: Request | string) { return this.map.get(key(req)); }
  async put(req: Request | string, res: Response) { this.map.set(key(req), res); }
  async delete(req: Request | string) { return this.map.delete(key(req)); }
  async keys() { return Array.from(this.map.keys()); }
  async addAll() { /* shell precache: not under test */ }
}
const key = (r: Request | string) => (typeof r === 'string' ? r : r.url);

type Harness = ReturnType<typeof loadSW>;

function loadSW() {
  const buckets = new Map<string, FakeCache>();
  const caches = {
    async open(name: string) {
      if (!buckets.has(name)) buckets.set(name, new FakeCache());
      return buckets.get(name)!;
    },
    async keys() { return Array.from(buckets.keys()); },
    async delete(name: string) { return buckets.delete(name); },
  };
  const handlers: Record<string, (e: any) => void> = {};
  const self = {
    addEventListener: (t: string, fn: (e: any) => void) => { handlers[t] = fn; },
    skipWaiting: () => Promise.resolve(),
    clients: { claim: () => Promise.resolve() },
    location: { origin: 'https://plan.example' },
  };
  // Network switch: tests flip it to simulate the link dropping.
  const net = { online: true, body: 'network' };
  const fetchMock = async () => {
    if (!net.online) throw new TypeError('Failed to fetch');
    return new Response(net.body, { status: 200 });
  };

  // eslint-disable-next-line no-new-func
  new Function('self', 'caches', 'fetch', SRC)(self, caches, fetchMock);

  async function get(path: string, token?: string) {
    const request = new Request(`https://plan.example${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    let responded: Promise<Response> | null = null;
    const waits: Promise<unknown>[] = [];
    handlers.fetch({ request, respondWith: (p: Promise<Response>) => { responded = p; },
                     waitUntil: (p: Promise<unknown>) => waits.push(p) });
    await Promise.all(waits);
    return responded as Promise<Response> | null;
  }

  return { buckets, caches, handlers, net, get };
}

let sw: Harness;
beforeEach(() => { sw = loadSW(); });

const apiBuckets = (h: Harness) => Array.from(h.buckets.keys())
  .filter((k) => k.includes('-api-'));

describe('service worker cache isolation', () => {
  it("does not serve one account's cached study to another account", async () => {
    sw.net.body = 'alice-coverage';
    const first = await sw.get('/api/rf/coverage/abc.json', 'ALICE');
    expect(await (await first!).text()).toBe('alice-coverage');

    // The link drops and Bob picks up the same tablet.
    sw.net.online = false;
    const bobs = await (await sw.get('/api/rf/coverage/abc.json', 'BOB'))!;
    const body = await bobs.json();
    expect(body.offline).toBe(true);
    expect(bobs.status).toBe(503);
  });

  it('still serves the offline fallback to the account that created it', async () => {
    sw.net.body = 'alice-coverage';
    await (await sw.get('/api/rf/coverage/abc.json', 'ALICE'))!;
    sw.net.online = false;
    const again = await (await sw.get('/api/rf/coverage/abc.json', 'ALICE'))!;
    expect(await again.text()).toBe('alice-coverage');
  });

  it('keeps the anonymous self-hosted session working', async () => {
    sw.net.body = 'open-mode';
    await (await sw.get('/api/rf/coverage/abc.json'))!;
    sw.net.online = false;
    const again = await (await sw.get('/api/rf/coverage/abc.json'))!;
    expect(await again.text()).toBe('open-mode');
    expect(apiBuckets(sw)).toEqual(['am-v2-api-anon']);
  });

  it('never stores identity, audit or live telemetry responses', async () => {
    for (const path of ['/api/auth/me', '/api/auth/audit', '/api/auth/export',
                        '/api/telemetry/state']) {
      // Declining to call respondWith is how a SW says "let the browser do
      // it" — no interception, no storage.
      expect(await sw.get(path, 'ALICE')).toBeNull();
    }
    expect(apiBuckets(sw)).toEqual([]);
  });

  it('purges every API bucket on sign-out, but keeps the offline basemap', async () => {
    await (await sw.get('/api/rf/coverage/abc.json', 'ALICE'))!;
    await (await sw.get('/api/projects', 'ALICE'))!;
    await (await sw.get('/api/basemap/11/1085/718.png'))!;   // a map tile
    expect(apiBuckets(sw).length).toBe(1);
    expect(sw.buckets.has('am-v2-tiles')).toBe(true);

    const waits: Promise<unknown>[] = [];
    sw.handlers.message({ data: { type: 'am-signout' },
                          waitUntil: (p: Promise<unknown>) => waits.push(p) });
    await Promise.all(waits);
    expect(apiBuckets(sw)).toEqual([]);
    // Tiles are public terrain, not customer data. Signing out must not cost
    // a field tablet the basemap it will need at the bottom of the pit.
    expect(sw.buckets.has('am-v2-tiles')).toBe(true);
  });

  it('retires the old unpartitioned cache when the worker upgrades', async () => {
    await sw.caches.open('am-v1-api');          // what the previous version wrote
    await sw.caches.open('am-v2-shell');
    const waits: Promise<unknown>[] = [];
    sw.handlers.activate({ waitUntil: (p: Promise<unknown>) => waits.push(p) });
    await Promise.all(waits);
    expect(Array.from(sw.buckets.keys())).not.toContain('am-v1-api');
    expect(Array.from(sw.buckets.keys())).toContain('am-v2-shell');
  });

  it('does not use the bearer token itself as a cache name', async () => {
    await (await sw.get('/api/projects', 'super-secret-token'))!;
    expect(apiBuckets(sw).join()).not.toContain('super-secret-token');
    // Cache names are readable by any script on the origin; a token there
    // would be a secret an XSS could simply enumerate.
    expect(apiBuckets(sw)[0]).toMatch(/^am-v2-api-[0-9a-f]{16}$/);
  });
});
