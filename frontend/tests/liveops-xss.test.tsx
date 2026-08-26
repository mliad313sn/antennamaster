/**
 * Regression: stored XSS through the Live Ops asset marker.
 *
 * Telemetry ingest is reachable over the network, and Leaflet's DivIcon
 * assigns its `html` option straight to innerHTML. An asset whose name was a
 * markup payload therefore executed in every open /live dashboard as soon as
 * the next SSE frame arrived. The name must be HTML-escaped at that sink.
 */
import { describe, expect, it } from 'vitest';

import { __escapeHtmlForTest as escapeHtml } from '@/components/LiveOps';

describe('Live Ops asset-name escaping', () => {
  it('neutralises a markup payload so no element can be created', () => {
    const payload = '"><img src=x onerror=alert(1)>';
    const escaped = escapeHtml(payload);

    // No raw angle brackets or quotes survive to break out of the attribute.
    expect(escaped).not.toContain('<');
    expect(escaped).not.toContain('>');
    expect(escaped).not.toContain('"');

    // Parsed as the browser would parse the marker, the payload is inert:
    // it yields no <img> element, and the name survives as text.
    const host = document.createElement('div');
    host.innerHTML = `<div class="asset-dot ok" title="${escaped}"></div>`;
    expect(host.querySelector('img')).toBeNull();
    expect(host.querySelectorAll('*').length).toBe(1);
    expect(host.firstElementChild!.getAttribute('title')).toBe(payload);
  });

  it('escapes the other HTML-significant characters', () => {
    expect(escapeHtml('a & b')).toBe('a &amp; b');
    expect(escapeHtml("it's")).toBe('it&#39;s');
    // Ampersands are escaped first, so an entity is not double-decoded.
    expect(escapeHtml('&lt;')).toBe('&amp;lt;');
  });

  it('leaves an ordinary asset name readable', () => {
    expect(escapeHtml('Truck 12')).toBe('Truck 12');
  });
});
