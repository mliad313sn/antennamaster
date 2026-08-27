/**
 * The offline base-map fallback must trigger on the internet actually being
 * unreachable — not on `navigator.onLine`.
 *
 * That flag reports whether a network interface exists, not whether the tile
 * provider can be reached, and every browser vendor documents it that way. The
 * two come apart in exactly the deployment this product targets: an OT/field
 * machine on a LAN with no route out, behind a corporate proxy, or on a
 * captive portal.
 *
 * Observed while driving the running app: `navigator.onLine === true` while
 * every CDN tile failed with ERR_TUNNEL_CONNECTION_FAILED. The fallback was
 * gated on that flag alone, so it never engaged: the planner drew a real
 * coverage study over a blank grey rectangle, with nothing on screen to say
 * the map — and only the map — was degraded.
 *
 * These tests pin the classifier that decides which failures count. It is the
 * whole hinge: count the wrong URLs and the local cache layer's own misses
 * trip the fallback, which then can never recover.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  TILE_FAILURES_BEFORE_FALLBACK, attachOfflineFallback, isRemoteTileUrl,
} from '@/components/MapView';

/** A Leaflet map and tile layer, reduced to what the fallback touches. */
function fakeStack(url = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png') {
  const handlers: Record<string, ((e: unknown) => void)[]> = {};
  const provider = {
    _url: url,
    getTileUrl: () => url,
    on: (t: string, f: (e: unknown) => void) => { (handlers[t] ??= []).push(f); },
    off: (t: string, f: (e: unknown) => void) => {
      handlers[t] = (handlers[t] ?? []).filter((h) => h !== f);
    },
  };
  const added: unknown[] = [];
  const map = {
    eachLayer: (fn: (l: unknown) => void) => [provider, ...added].forEach(fn),
    on: () => {},
    hasLayer: (l: unknown) => added.includes(l),
    addLayer: (l: unknown) => { added.push(l); },
    removeLayer: (l: unknown) => { added.splice(added.indexOf(l), 1); },
  };
  const fire = (t: string, n = 1) => {
    for (let i = 0; i < n; i++) (handlers[t] ?? []).forEach((h) => h({ target: provider }));
  };
  return { map, fire, cacheLayersOnMap: () => added.length };
}

describe('which tile failures mean "the internet is unreachable"', () => {
  it('counts the remote providers the app actually ships', () => {
    for (const url of [
      'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
      'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
      'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      'http://tiles.example.internal/{z}/{x}/{y}.png',   // a custom provider
    ]) {
      expect(isRemoteTileUrl(url), url).toBe(true);
    }
  });

  it('does NOT count the local cache layer, which is the fallback itself', () => {
    // Counting these is self-defeating: the fallback layer is served by our
    // own backend, so on a cold cache its misses would push the failure count
    // up forever and the state could never clear.
    expect(isRemoteTileUrl('/api/basemap/{z}/{x}/{y}.png')).toBe(false);
    expect(isRemoteTileUrl('/api/basemap/{z}/{x}/{y}.png?offline=true')).toBe(false);
    expect(isRemoteTileUrl('http://localhost:3010/api/basemap/1/2/3.png')).toBe(false);
  });

  it('does not fall over on a layer with no URL', () => {
    expect(isRemoteTileUrl(undefined)).toBe(false);
    expect(isRemoteTileUrl('')).toBe(false);
  });

  it('needs more than one failure, but less than a screenful', () => {
    // One 404 at the edge of a provider's coverage is normal and must not
    // swap the user's chosen base map out from under them; a full viewport is
    // ~20 tiles, so the threshold has to be well under that to be useful.
    expect(TILE_FAILURES_BEFORE_FALLBACK).toBeGreaterThan(1);
    expect(TILE_FAILURES_BEFORE_FALLBACK).toBeLessThan(20);
  });
});

describe('the fallback engages on unreachable tiles, not on navigator.onLine', () => {
  beforeEach(() => {
    // The exact condition that defeated the old implementation: the browser
    // insists it is online while nothing can actually be fetched.
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
  });

  it('swaps in the cached layer once enough remote tiles fail', () => {
    const { map, fire, cacheLayersOnMap } = fakeStack();
    const degraded: boolean[] = [];
    const detach = attachOfflineFallback(map, (v) => degraded.push(v));

    fire('tileerror', TILE_FAILURES_BEFORE_FALLBACK - 1);
    expect(cacheLayersOnMap(), 'gave up before the threshold').toBe(0);
    expect(degraded).toEqual([]);

    fire('tileerror', 1);
    expect(cacheLayersOnMap(), 'the cached base map never went on the map').toBe(1);
    expect(degraded, 'the user was never told the map was degraded').toEqual([true]);
    detach();
  });

  it('takes the cached layer away again when a real tile loads', () => {
    const { map, fire, cacheLayersOnMap } = fakeStack();
    const degraded: boolean[] = [];
    const detach = attachOfflineFallback(map, (v) => degraded.push(v));

    fire('tileerror', TILE_FAILURES_BEFORE_FALLBACK);
    expect(cacheLayersOnMap()).toBe(1);

    fire('tileload', 1);            // connectivity came back
    expect(cacheLayersOnMap(), 'the overlay outlived the outage').toBe(0);
    expect(degraded).toEqual([true, false]);
    detach();
  });

  it('ignores failures from the local cache layer itself', () => {
    // Otherwise a cold cache feeds the counter from the very layer the
    // fallback installs, and the state can never clear.
    const { map, fire, cacheLayersOnMap } = fakeStack('/api/basemap/{z}/{x}/{y}.png?offline=true');
    const detach = attachOfflineFallback(map);
    fire('tileerror', TILE_FAILURES_BEFORE_FALLBACK * 3);
    expect(cacheLayersOnMap()).toBe(0);
    detach();
  });

  it('leaves nothing on the map after unmount', () => {
    const { map, fire, cacheLayersOnMap } = fakeStack();
    const detach = attachOfflineFallback(map);
    fire('tileerror', TILE_FAILURES_BEFORE_FALLBACK);
    expect(cacheLayersOnMap()).toBe(1);
    detach();
    expect(cacheLayersOnMap(), 'the fallback layer leaked past unmount').toBe(0);
  });
});

describe('threshold sanity', () => {
  it('is a usable number', () => {
    // One 404 at the edge of a provider's coverage is normal and must not
    // swap the user's chosen base map out from under them; a full viewport is
    // ~20 tiles, so the threshold has to be well under that to be useful.
    expect(TILE_FAILURES_BEFORE_FALLBACK).toBeGreaterThan(1);
    expect(TILE_FAILURES_BEFORE_FALLBACK).toBeLessThan(20);
  });
});
