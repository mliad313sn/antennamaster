'use client';

/**
 * Live Operations — the digital-twin dashboard.
 *
 * Streams live asset positions from the telemetry engine (SSE, with a polling
 * fallback) and renders them on the map. Assets are colour-coded by their RF
 * status: green = in coverage, YELLOW (pulsing) = inside a predicted dead
 * zone, grey = stopped transmitting. Correlation events — dead-zone entries
 * and RF-disconnects — stream into an event log. A built-in demo feeder posts
 * a synthetic moving asset so the correlation is visible without a real FMS.
 */
import L from 'leaflet';
import { useEffect, useRef, useState } from 'react';
import { MapContainer, Marker, Polyline, TileLayer } from 'react-leaflet';
import { useTranslation } from 'react-i18next';
import { authHeaders, getToken } from '@/lib/saas';

type Asset = {
  asset_id: string; lat: number; lon: number; name: string;
  transmitting: boolean; in_dead_zone: boolean; margin_db: number | null;
  track: number[][];
};
type Ev = { seq: number; type: string; asset_id: string; name: string; at: number; correlation?: string };

/** Escape text destined for an HTML string sink.
 *
 *  Leaflet's DivIcon assigns `html` straight to innerHTML, so an asset name is
 *  attacker-controlled markup unless escaped: telemetry is ingested over the
 *  network, and a name like `"><img src=x onerror=...>` would execute in every
 *  open Live Ops dashboard the moment the next frame arrived (stored XSS).
 *  Everything else in this file renders through React, which escapes for us. */
function escapeHtml(s: string): string {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function assetIcon(a: Asset): L.DivIcon {
  const cls = !a.transmitting ? 'down' : a.in_dead_zone ? 'dead' : 'ok';
  return L.divIcon({
    className: '', iconSize: [18, 18], iconAnchor: [9, 9],
    html: `<div class="asset-dot ${cls}" title="${escapeHtml(a.name)}"></div>`,
  });
}

export { escapeHtml as __escapeHtmlForTest };

export default function LiveOps() {
  const { t } = useTranslation();
  const [assets, setAssets] = useState<Asset[]>([]);
  const [events, setEvents] = useState<Ev[]>([]);
  const [tech, setTech] = useState('pmr446');
  const [txLat, setTxLat] = useState('47.05');
  const [txLon, setTxLon] = useState('15.05');
  const [ctxSet, setCtxSet] = useState(false);
  const demoRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [demoOn, setDemoOn] = useState(false);

  // Live feed: SSE first, fall back to polling if the stream errors.
  useEffect(() => {
    let es: EventSource | null = null;
    let poll: ReturnType<typeof setInterval> | null = null;
    let cursor = 0;
    const startPolling = () => {
      if (poll) return;
      poll = setInterval(async () => {
        try {
          const s = await fetch('/api/telemetry/state',
            { headers: authHeaders() }).then((r) => r.json());
          setAssets(s.assets ?? []);
          const ev = await fetch(`/api/telemetry/events?since=${cursor}`,
            { headers: authHeaders() }).then((r) => r.json());
          if (ev.events?.length) {
            cursor = ev.event_seq;
            setEvents((prev) => [...ev.events, ...prev].slice(0, 40));
          }
        } catch { /* keep trying */ }
      }, 1500);
    };
    // A stream that CONNECTS but never delivers is the dangerous case, and
    // it is the common one: anything between the browser and the backend that
    // buffers - Next's own gzip, nginx without `proxy_buffering off`, a
    // corporate proxy - holds every frame of an infinite response forever.
    // `onerror` never fires, so the fallback below never engaged and the
    // dashboard sat silently empty. Measured through the app's own proxy:
    // the backend delivered the first frame in 0.0 s while the browser
    // received nothing at all. So the stream now has to PROVE it works.
    let firstFrame: ReturnType<typeof setTimeout> | null = null;
    const streamIsAlive = () => {
      if (firstFrame) { clearTimeout(firstFrame); firstFrame = null; }
    };
    try {
      // EventSource cannot set headers, so in multi-tenant mode the token
      // travels as a query parameter (the backend accepts either).
      const tok = getToken();
      es = new EventSource('/api/telemetry/stream'
        + (tok ? `?token=${encodeURIComponent(tok)}` : ''));
      firstFrame = setTimeout(() => {
        es?.close(); es = null;
        startPolling();
      }, 4000);
      es.addEventListener('state', (e) => {
        streamIsAlive();
        try { setAssets(JSON.parse((e as MessageEvent).data).assets ?? []); }
        catch { /* ignore a malformed frame; the next one recovers */ }
      });
      es.addEventListener('correlation', (e) => {
        streamIsAlive();
        try {
          const ev = JSON.parse((e as MessageEvent).data);
          setEvents((prev) => [ev, ...prev].slice(0, 40));
        } catch { /* ignore a malformed frame */ }
      });
      es.onerror = () => { streamIsAlive(); es?.close(); es = null; startPolling(); };
    } catch { startPolling(); }
    return () => {
      if (firstFrame) clearTimeout(firstFrame);
      es?.close();
      if (poll) clearInterval(poll);
    };
  }, []);

  async function bindCoverage() {
    await fetch('/api/telemetry/coverage-context', {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ tx_lat: +txLat, tx_lon: +txLon, technology: tech }),
    });
    setCtxSet(true);
  }

  // Demo feeder: walk an asset east from the TX until it leaves coverage,
  // then stop transmitting (to trigger an RF-disconnect correlation).
  function toggleDemo() {
    if (demoOn) {
      if (demoRef.current) clearInterval(demoRef.current);
      demoRef.current = null; setDemoOn(false); return;
    }
    let step = 0;
    demoRef.current = setInterval(async () => {
      step += 1;
      if (step > 20) { // stop transmitting -> disconnect after a while
        if (demoRef.current) clearInterval(demoRef.current);
        demoRef.current = null; setDemoOn(false); return;
      }
      const lon = +txLon + step * 0.03;
      await fetch('/api/telemetry/ingest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ pings: [{ asset_id: 'demo-truck', name: 'Demo Truck', lat: +txLat, lon }] }),
      }).catch(() => {});
    }, 900);
    setDemoOn(true);
  }

  const center: [number, number] = [+txLat || 47.05, +txLon || 15.05];
  return (
    <div className="liveops">
      <div className="liveops-side">
        <h2>{t('liveops.title')}</h2>
        <p className="hint">{t('liveops.intro')}</p>
        <div className="field-grid">
          <label>{t('liveops.txLat')}<input value={txLat} onChange={(e) => setTxLat(e.target.value)} /></label>
          <label>{t('liveops.txLon')}<input value={txLon} onChange={(e) => setTxLon(e.target.value)} /></label>
          <label>{t('liveops.technology')}
            <select value={tech} onChange={(e) => setTech(e.target.value)}>
              <option value="pmr446">PMR446</option>
              <option value="tetra400">TETRA 400</option>
              <option value="vhf150">VHF 150</option>
              <option value="private_lte_b48">Private LTE B48</option>
            </select>
          </label>
        </div>
        <button className="primary" style={{ width: '100%' }} onClick={bindCoverage}>
          {ctxSet ? t('liveops.ctxUpdate') : t('liveops.ctxBind')}
        </button>
        <button style={{ width: '100%', marginTop: 8 }} onClick={toggleDemo}>
          {demoOn ? t('liveops.demoStop') : t('liveops.demoStart')}
        </button>

        <div className="legend-row">
          <span><i className="asset-dot ok" /> {t('liveops.inCoverage')}</span>
          <span><i className="asset-dot dead" /> {t('liveops.deadZone')}</span>
          <span><i className="asset-dot down" /> {t('liveops.disconnected')}</span>
        </div>

        <h3>{t('liveops.assets')} ({assets.length})</h3>
        <ul className="asset-list">
          {assets.map((a) => (
            <li key={a.asset_id} className={!a.transmitting ? 'down' : a.in_dead_zone ? 'dead' : ''}>
              <b>{a.name}</b> · {a.margin_db != null ? `${a.margin_db} dB` : '—'}
              {a.in_dead_zone && a.transmitting && ` · ${t('liveops.deadZone')}`}
              {!a.transmitting && ` · ${t('liveops.disconnected')}`}
            </li>
          ))}
        </ul>

        <h3>{t('liveops.events')}</h3>
        <ul className="event-list">
          {events.map((e) => (
            <li key={e.seq} className={e.type}>
              <b>{eventLabel(e.type, t)}</b> — {e.name}
              {e.correlation && ` (${e.correlation})`}
            </li>
          ))}
          {!events.length && <li className="muted">{t('liveops.noEvents')}</li>}
        </ul>
      </div>
      <div className="liveops-map">
        <MapContainer center={center} zoom={11} preferCanvas style={{ height: '100%', width: '100%' }}>
          <TileLayer url="/api/basemap/{z}/{x}/{y}.png" />
          {assets.map((a) => (
            <Marker key={a.asset_id} position={[a.lat, a.lon]} icon={assetIcon(a)} />
          ))}
          {assets.filter((a) => a.track.length > 1).map((a) => (
            <Polyline key={`t-${a.asset_id}`} positions={a.track.map((p) => [p[0], p[1]] as [number, number])}
              pathOptions={{ color: a.in_dead_zone ? '#e5b100' : '#2a78d6', weight: 2, opacity: 0.6 }} />
          ))}
        </MapContainer>
      </div>
    </div>
  );
}

function eventLabel(type: string, t: (k: string) => string): string {
  const map: Record<string, string> = {
    enter_dead_zone: 'liveops.evEnter', exit_dead_zone: 'liveops.evExit',
    rf_disconnect: 'liveops.evDisconnect', asset_online: 'liveops.evOnline',
    asset_reconnect: 'liveops.evReconnect',
  };
  return map[type] ? t(map[type]) : type;
}
