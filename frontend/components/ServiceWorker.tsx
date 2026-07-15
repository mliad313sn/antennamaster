'use client';

import { useEffect } from 'react';

/**
 * Registers the offline service worker (production only — the dev server's
 * hot-reload and a cache-first SW fight each other).  Silent no-op where
 * service workers are unavailable.
 */
export default function ServiceWorker() {
  useEffect(() => {
    if (process.env.NODE_ENV !== 'production') return;
    if (!('serviceWorker' in navigator)) return;
    const onLoad = () => {
      navigator.serviceWorker.register('/sw.js').catch(() => {
        /* registration failure is non-fatal: the app just isn't offline-ready */
      });
    };
    if (document.readyState === 'complete') onLoad();
    else window.addEventListener('load', onLoad, { once: true });
    return () => window.removeEventListener('load', onLoad);
  }, []);
  return null;
}
