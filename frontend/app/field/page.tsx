'use client';

/**
 * Tactical View — the field technician's mobile screen: forced high-contrast
 * dark UI, GPS spot check (where am I, what's the ground elevation, does the
 * link to my saved TX work from here), and one-tap technology presets.
 */
import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import DashNav from '@/components/DashNav';

interface Spot {
  lat: number;
  lon: number;
  elevation_m?: number;
  accuracy_m?: number;
}

const QUICK_PRESETS = [
  { key: 'vhf150', label: 'VHF 150' },
  { key: 'pmr446', label: 'PMR446' },
  { key: 'tetra400', label: 'TETRA' },
  { key: 'ptp18000', label: 'µW PtP' },
  { key: 'wifi5800', label: 'Wi-Fi 5.8' },
  { key: 'private_lte_b48', label: 'CBRS LTE' },
];

export default function Field() {
  const { t } = useTranslation();
  const [spot, setSpot] = useState<Spot | null>(null);
  const [watching, setWatching] = useState(false);
  const watchId = useRef<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [online, setOnline] = useState(true);

  // Live connectivity state — field engineers work off-grid; the app is
  // cached for offline use and this makes the current state explicit.
  useEffect(() => {
    const sync = () => setOnline(navigator.onLine);
    sync();
    window.addEventListener('online', sync);
    window.addEventListener('offline', sync);
    return () => {
      window.removeEventListener('online', sync);
      window.removeEventListener('offline', sync);
    };
  }, []);

  // Force dark theme for sunlight-readable high contrast on site.
  useEffect(() => {
    const prev = document.documentElement.getAttribute('data-theme');
    document.documentElement.setAttribute('data-theme', 'dark');
    return () => {
      if (prev) document.documentElement.setAttribute('data-theme', prev);
      else document.documentElement.removeAttribute('data-theme');
    };
  }, []);

  async function locate(follow = false) {
    if (!navigator.geolocation) { setError(t('field.noGps')); return; }
    setError(null);
    const handle = async (pos: GeolocationPosition) => {
      const { latitude, longitude, accuracy } = pos.coords;
      const next: Spot = { lat: latitude, lon: longitude, accuracy_m: accuracy };
      try {
        const resp = await fetch(`/api/terrain/elevation?lat=${latitude}&lon=${longitude}`);
        if (resp.ok) next.elevation_m = (await resp.json()).elevation_m;
      } catch { /* offline: coordinates still useful */ }
      setSpot(next);
    };
    if (follow) {
      setWatching(true);
      watchId.current = navigator.geolocation.watchPosition(handle,
        (e) => { setError(e.message); stopFollowing(); },
        { enableHighAccuracy: true });
    } else {
      navigator.geolocation.getCurrentPosition(handle,
        (e) => setError(e.message), { enableHighAccuracy: true });
    }
  }

  function stopFollowing() {
    if (watchId.current !== null) {
      navigator.geolocation.clearWatch(watchId.current);
      watchId.current = null;
    }
    setWatching(false);
  }

  // Never leak the GPS watcher past this page's lifetime.
  useEffect(() => stopFollowing, []); // eslint-disable-line react-hooks/exhaustive-deps

  function openPlannerHere(preset?: string) {
    // Seed the planner session so the map opens on this spot with the preset.
    try {
      const raw = localStorage.getItem('am_session_v1');
      const s = raw ? JSON.parse(raw) : {};
      if (spot) {
        s.rx = { lat: spot.lat, lng: spot.lon };
        localStorage.setItem('am_view', JSON.stringify({ lat: spot.lat, lng: spot.lon, z: 14 }));
      }
      if (preset) s.technology = preset;
      localStorage.setItem('am_session_v1', JSON.stringify(s));
    } catch { /* storage unavailable */ }
    window.location.href = '/';
  }

  return (
    <div className="dash-shell field-shell">
      <DashNav active="field" />
      <main id="main" className="dash-main tactical">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <h1 style={{ margin: 0 }}>{t('field.title')}</h1>
          <span className={`conn-pill ${online ? 'on' : 'off'}`}>
            {online ? t('field.online') : t('field.offline')}
          </span>
        </div>
        <p className="hint">{t('field.intro')}
          {!online && t('field.offlineNote')}</p>

        <div className="row">
          <button className="primary tactical-btn" onClick={() => locate(false)}>
            📍 {t('field.spotCheck')}
          </button>
          <button className="tactical-btn"
            onClick={() => (watching ? stopFollowing() : locate(true))}>
            {watching ? `⏹ ${t('field.stopFollowing')}` : `👣 ${t('field.followMe')}`}
          </button>
        </div>

        {spot && (
          <section className="panel tactical-readout">
            <div className="kpi-row">
              <div className="kpi"><div className="kpi-v">{spot.lat.toFixed(5)}</div><div className="kpi-k">{t('field.latitude')}</div></div>
              <div className="kpi"><div className="kpi-v">{spot.lon.toFixed(5)}</div><div className="kpi-k">{t('field.longitude')}</div></div>
              <div className="kpi"><div className="kpi-v">{spot.elevation_m !== undefined ? `${spot.elevation_m.toFixed(0)} m` : '—'}</div><div className="kpi-k">{t('field.groundAsl')}</div></div>
              <div className="kpi"><div className="kpi-v">{spot.accuracy_m ? `±${spot.accuracy_m.toFixed(0)} m` : '—'}</div><div className="kpi-k">{t('field.gpsAccuracy')}</div></div>
            </div>
            <button className="primary tactical-btn" style={{ width: '100%' }}
              onClick={() => openPlannerHere()}>
              {t('field.useAsRx')}
            </button>
          </section>
        )}

        <h3 style={{ marginTop: 16 }}>{t('field.quickPresets')}</h3>
        <div className="tactical-grid">
          {QUICK_PRESETS.map((p) => (
            <button key={p.key} className="tactical-btn"
              onClick={() => openPlannerHere(p.key)}>
              {p.label}
            </button>
          ))}
        </div>

        {error && <div className="error-box" role="alert">{error}</div>}
        <p className="hint" style={{ marginTop: 14 }}>
          {t('field.plannerNote')} <Link href="/">{t('field.plannerLink')}</Link>
        </p>
      </main>
    </div>
  );
}
