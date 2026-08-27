/**
 * A signed-in user must be able to see and download their own coverage.
 *
 * Coverage results are owner-scoped — a result id is not a capability, since
 * it travels in share links, PDF footers, audit fields and proxy logs, and
 * treating it as authorisation leaked other tenants' georeferenced site
 * footprints. The backend therefore answers 404 to anyone who is not the
 * owner, which is right.
 *
 * The gap was on this side: the browser loaded the raster as an `<img>`
 * (Leaflet's ImageOverlay, Cesium's single tile) and offered the exports as
 * `<a download href>`. Neither can carry a header, and the token lives in
 * localStorage rather than a cookie — so a signed-in user's request for their
 * OWN result arrived unauthenticated and was refused. Measured against the
 * running stack on a freshly computed study:
 *
 *     .png as an <img> -> 404,  with the bearer -> 200
 *     .tif as an <a>   -> 404,  with the bearer -> 200
 *     .kmz as an <a>   -> 404,  with the bearer -> 200
 *
 * and the overlay element sat in the DOM with naturalWidth 0. The product's
 * central output was invisible and undownloadable for every account holder,
 * while anonymous self-hosted use kept working — so no test and no amount of
 * unauthenticated clicking would have shown it.
 *
 * The credential must NOT move into the URL: the backend's own docstring says
 * these URLs end up in proxy logs and share links, and a bearer token there is
 * strictly worse than the id it protects.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { downloadAsset, fetchObjectUrl } from '@/lib/authedAsset';

const TOKEN = 'tok-abc123';
const URL_PNG = '/api/rf/coverage/59f41d8b584b.png';

beforeEach(() => {
  localStorage.setItem('am_token', TOKEN);
  vi.stubGlobal('URL', Object.assign(globalThis.URL, {
    createObjectURL: vi.fn(() => 'blob:mock/1'),
    revokeObjectURL: vi.fn(),
  }));
});
afterEach(() => { localStorage.clear(); vi.restoreAllMocks(); });

describe('loading an owner-scoped raster', () => {
  it('sends the bearer token', async () => {
    const f = vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(['x']) });
    vi.stubGlobal('fetch', f);
    await fetchObjectUrl(URL_PNG);
    const [url, init] = f.mock.calls[0];
    expect(url).toBe(URL_PNG);
    expect(init.headers).toEqual({ Authorization: `Bearer ${TOKEN}` });
  });

  it('never puts the token in the URL', async () => {
    // The alternative fix, and the wrong one: these URLs are logged by proxies
    // and pasted into share links, so a token there is worse than the id.
    const f = vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(['x']) });
    vi.stubGlobal('fetch', f);
    await fetchObjectUrl(URL_PNG);
    expect(String(f.mock.calls[0][0])).not.toContain(TOKEN);
    expect(String(f.mock.calls[0][0])).not.toMatch(/token=/i);
  });

  it('raises rather than handing back a broken image', async () => {
    // Previously the 404 body became the <img> src and painted nothing, with
    // naturalWidth 0 and no error anywhere. A rejection is what lets the UI
    // say something.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }));
    await expect(fetchObjectUrl(URL_PNG)).rejects.toThrow(/404/);
  });
});

describe('downloading an owner-scoped export', () => {
  it('fetches with credentials instead of navigating to the URL', async () => {
    // An <a download> saved the body of a 404 under the right filename: a
    // "coverage.kmz" that Google Earth refuses to open, silently.
    const f = vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(['x']) });
    vi.stubGlobal('fetch', f);
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {});
    await downloadAsset('/api/rf/coverage/59f41d8b584b.kmz');
    expect(f).toHaveBeenCalledWith('/api/rf/coverage/59f41d8b584b.kmz',
      expect.objectContaining({ headers: { Authorization: `Bearer ${TOKEN}` } }));
    expect(click).toHaveBeenCalled();
  });

  it('propagates a failure so the panel can show it', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 402 }));
    await expect(downloadAsset('/api/rf/coverage/x.tif')).rejects.toThrow(/402/);
  });

  it('works anonymously too — no header, same call', async () => {
    // Self-hosted installs have no account and their results have no owner.
    localStorage.clear();
    const f = vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(['x']) });
    vi.stubGlobal('fetch', f);
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    await downloadAsset(URL_PNG);
    expect(f.mock.calls[0][1].headers).toEqual({});
  });
});
