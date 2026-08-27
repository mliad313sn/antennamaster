/**
 * Load a stored raster that belongs to an account.
 *
 * THE PROBLEM THIS SOLVES. Coverage results are owner-scoped: a result id is
 * not a capability, because it travels in share links, PDF footers, audit
 * fields and proxy logs, and treating it as authorisation leaked other
 * tenants' georeferenced site footprints. So the backend answers 404 to
 * anyone who is not the owner — correctly.
 *
 * But the browser loads a raster as an `<img>` (Leaflet's ImageOverlay,
 * Cesium's single-tile imagery) or as `<a download href>`, and neither can
 * carry a header. The token lives in localStorage, not a cookie. So a
 * signed-in user's request for their OWN result arrived unauthenticated and
 * the backend refused it — exactly as designed, and exactly wrong for them.
 *
 * Measured against the running stack, signed in, on a freshly computed study:
 *
 *     .png  as an <img>  -> 404      with the bearer -> 200
 *     .tif  as an <a>    -> 404      with the bearer -> 200
 *     .kmz  as an <a>    -> 404      with the bearer -> 200
 *
 * The coverage overlay element was present in the DOM with naturalWidth 0 — a
 * broken image, nothing painted. The product's central output was invisible
 * and undownloadable for every account holder, while anonymous self-hosted
 * use (results with no owner) worked fine.
 *
 * THE FIX, AND WHY NOT THE OBVIOUS ONE. The token could ride in the query
 * string, as the SSE stream already does. Not here: the docstring on the
 * backend's own `resolve_result` explains that these URLs end up in proxy
 * logs and share links, and putting a bearer token there is strictly worse
 * than the id it was protecting. So fetch with the header and hand the
 * browser a blob instead — the credential never enters a URL.
 */
import { useEffect, useState } from 'react';

import { authHeaders } from '@/lib/saas';

/** Fetch `url` with the account's credentials and return an object URL.
 *  The caller owns the result and must revoke it. */
export async function fetchObjectUrl(url: string): Promise<string> {
  const r = await fetch(url, { headers: authHeaders(), cache: 'no-store' });
  if (!r.ok) throw new Error(`${r.status} loading ${url}`);
  return URL.createObjectURL(await r.blob());
}

/**
 * An object URL for `url`, refetched when it changes and revoked when it is
 * replaced or the component unmounts. `null` while loading or on failure —
 * callers render nothing rather than a broken image.
 *
 * Anonymous deployments send no header and get the same bytes, so this is not
 * a SaaS-only path: it is simply how a stored raster is loaded now.
 */
export function useAuthedAsset(url: string | null | undefined): string | null {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!url) { setObjectUrl(null); return; }
    let revoked = false;
    let mine: string | null = null;
    fetchObjectUrl(url).then((o) => {
      if (revoked) { URL.revokeObjectURL(o); return; }
      mine = o;
      setObjectUrl(o);
    }).catch(() => setObjectUrl(null));
    return () => {
      revoked = true;
      if (mine) URL.revokeObjectURL(mine);   // or the blob leaks for the tab's life
      setObjectUrl(null);
    };
  }, [url]);
  return objectUrl;
}

/** Save an owner-scoped artefact to disk. Replaces `<a download href=…>`,
 *  which cannot authenticate and so downloaded a 404 body under the right
 *  filename — a "coverage.kmz" that Google Earth refuses to open. */
export async function downloadAsset(url: string, filename?: string): Promise<void> {
  const object = await fetchObjectUrl(url);
  try {
    const a = document.createElement('a');
    a.href = object;
    a.download = filename || url.split('/').pop() || 'download';
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    // Give the navigation a tick before the blob disappears underneath it.
    setTimeout(() => URL.revokeObjectURL(object), 30_000);
  }
}
