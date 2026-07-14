'use client';

/**
 * Main screen: sidebar (link parameters + DXF import + validation results),
 * Leaflet map (TX/RX placement, DXF footprint + hillshade overlay) and the
 * provenance-colored elevation profile chart.
 */
import dynamic from 'next/dynamic';
import { useCallback, useEffect, useState } from 'react';
import DxfWizard from '@/components/DxfWizard';
import ProfileChart from '@/components/ProfileChart';
import { fetchProfile } from '@/lib/api';
import type { GeorefResponse, LatLng, ProfileResponse } from '@/lib/types';

// Leaflet accesses `window` at import time — client-only.
const MapView = dynamic(() => import('@/components/MapView'), {
  ssr: false,
  loading: () => <div style={{ padding: 20, color: 'var(--ink-muted)' }}>Loading map…</div>,
});

export default function Home() {
  const [tx, setTx] = useState<LatLng | null>(null);
  const [rx, setRx] = useState<LatLng | null>(null);
  const [placing, setPlacing] = useState<'tx' | 'rx' | null>('tx');

  const [txHeight, setTxHeight] = useState(20);
  const [rxHeight, setRxHeight] = useState(10);
  const [freqMhz, setFreqMhz] = useState(446);

  const [wizardOpen, setWizardOpen] = useState(false);
  const [georef, setGeoref] = useState<GeorefResponse | null>(null);
  const [showOverlay, setShowOverlay] = useState(true);

  const [profile, setProfile] = useState<ProfileResponse | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handlePlace = useCallback((p: LatLng) => {
    if (placing === 'tx') {
      setTx(p);
      setPlacing('rx');
    } else if (placing === 'rx') {
      setRx(p);
      setPlacing(null);
    }
  }, [placing]);

  // Recompute the profile whenever endpoints, RF params or the DXF change.
  useEffect(() => {
    if (!tx || !rx) return;
    let cancelled = false;
    setLoading(true);
    setProfileError(null);
    fetchProfile({
      lat1: tx.lat, lon1: tx.lng, lat2: rx.lat, lon2: rx.lng,
      dxfId: georef?.dxf_id ?? null,
      txHeight, rxHeight, freqMhz,
    })
      .then((p) => { if (!cancelled) setProfile(p); })
      .catch((e) => { if (!cancelled) setProfileError((e as Error).message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [tx, rx, txHeight, rxHeight, freqMhz, georef]);

  const validation = georef?.validation;
  const transform = georef?.transform;

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>AntennaMaster</h1>
        <span className="sub">Terrain &amp; georeferencing — SRTM 30 m base + DXF high-res patch</span>
      </header>

      <div className="app-main">
        <aside className="sidebar">
          <div className="panel">
            <h3>Link endpoints</h3>
            <div className="row">
              <button
                className={placing === 'tx' ? 'primary' : ''}
                onClick={() => setPlacing('tx')}
              >
                {tx ? '↺ Move TX' : 'Place TX'}
              </button>
              <button
                className={placing === 'rx' ? 'primary' : ''}
                onClick={() => setPlacing('rx')}
              >
                {rx ? '↺ Move RX' : 'Place RX'}
              </button>
            </div>
            {tx && <div className="stat-line"><span className="k">TX</span><span className="v">{tx.lat.toFixed(5)}, {tx.lng.toFixed(5)}</span></div>}
            {rx && <div className="stat-line"><span className="k">RX</span><span className="v">{rx.lat.toFixed(5)}, {rx.lng.toFixed(5)}</span></div>}
            <div className="row" style={{ marginTop: 8 }}>
              <div>
                <label>TX height (m)</label>
                <input type="number" min={0} value={txHeight}
                  onChange={(e) => setTxHeight(parseFloat(e.target.value) || 0)} />
              </div>
              <div>
                <label>RX height (m)</label>
                <input type="number" min={0} value={rxHeight}
                  onChange={(e) => setRxHeight(parseFloat(e.target.value) || 0)} />
              </div>
            </div>
            <div>
              <label>Frequency (MHz)</label>
              <input type="number" min={1} value={freqMhz}
                onChange={(e) => setFreqMhz(parseFloat(e.target.value) || 1)} />
            </div>
          </div>

          <div className="panel">
            <h3>Local DXF terrain</h3>
            {!georef && (
              <>
                <p className="hint">
                  No DXF loaded — profiles use global SRTM only. Import a survey
                  DXF to patch high-resolution relief over the base terrain.
                </p>
                <button className="primary" style={{ width: '100%' }} onClick={() => setWizardOpen(true)}>
                  Import DXF…
                </button>
              </>
            )}
            {georef && transform && (
              <>
                <div className="stat-line"><span className="k">Mode</span><span className="v">{String(transform.mode)}</span></div>
                <div className="stat-line"><span className="k">Grid</span><span className="v">{georef.grid.nx}×{georef.grid.ny} @ {georef.grid.cell_size_m.toFixed(1)} m</span></div>
                <div className="stat-line"><span className="k">Points used</span><span className="v">{georef.grid.points_used.toLocaleString()}</span></div>
                {typeof transform.rms_residual_m === 'number' && (
                  <div className="stat-line">
                    <span className="k">Helmert RMS residual</span>
                    <span className="v" style={{ color: transform.rms_residual_m > 10 ? 'var(--status-critical)' : 'var(--status-good)' }}>
                      {transform.rms_residual_m.toFixed(2)} m
                    </span>
                  </div>
                )}
                {Array.isArray(transform.residuals_m) && (
                  <div className="stat-line">
                    <span className="k">Per-point residuals</span>
                    <span className="v">{(transform.residuals_m as number[]).map((r) => r.toFixed(1)).join(' / ')} m</span>
                  </div>
                )}
                {validation && typeof validation.mean_diff_m === 'number' && (
                  <div className="stat-line">
                    <span className="k">DXF − SRTM mean</span>
                    <span className="v">{validation.mean_diff_m.toFixed(1)} m</span>
                  </div>
                )}
                <div className="row" style={{ marginTop: 8 }}>
                  <button onClick={() => setShowOverlay((v) => !v)}>
                    {showOverlay ? 'Hide overlay' : 'Show overlay'}
                  </button>
                  <button onClick={() => { setGeoref(null); setProfile(null); }}>
                    Remove DXF
                  </button>
                </div>
                <button style={{ width: '100%', marginTop: 8 }} onClick={() => setWizardOpen(true)}>
                  Import another DXF…
                </button>
              </>
            )}
          </div>

          {validation?.warning && (
            <div className="warning-box">
              <b>⚠ Terrain validation warning</b><br />
              {validation.warning}
            </div>
          )}
          {validation?.error && (
            <div className="warning-box">
              <b>⚠</b> {validation.error}
            </div>
          )}

          {profile && (
            <div className="panel">
              <h3>Link analysis</h3>
              <div className="stat-line"><span className="k">Distance</span><span className="v">{(profile.distance_m / 1000).toFixed(2)} km</span></div>
              <div className="stat-line">
                <span className="k">Line of sight</span>
                <span className="v" style={{ color: profile.rf.line_of_sight_clear ? 'var(--status-good)' : 'var(--status-critical)' }}>
                  {profile.rf.line_of_sight_clear ? 'Clear' : 'Obstructed'}
                </span>
              </div>
              <div className="stat-line"><span className="k">Knife-edge loss</span><span className="v">{profile.rf.knife_edge_loss_db.toFixed(1)} dB</span></div>
              <div className="stat-line"><span className="k">F1 clearance</span><span className="v">{(profile.rf.fresnel_clearance_ratio * 100).toFixed(0)}%</span></div>
              <div className="stat-line"><span className="k">k-factor</span><span className="v">{profile.rf.k_factor.toFixed(2)}</span></div>
              <div style={{ marginTop: 6, fontSize: 11 }}>
                <span className="badge srtm">SRTM</span>{' '}
                <span className="badge dxf">DXF</span>{' '}
                <span style={{ color: 'var(--ink-muted)' }}>= data provenance in the chart</span>
              </div>
            </div>
          )}
          {profileError && <div className="error-box">{profileError}</div>}
        </aside>

        <div className="map-and-chart">
          <div className="map-wrap">
            <MapView
              tx={tx} rx={rx} placing={placing} onPlace={handlePlace}
              georef={georef} showOverlay={showOverlay}
            />
          </div>
          {(profile || loading) && (
            <div className="chart-wrap">
              {profile
                ? <ProfileChart profile={profile} />
                : <div style={{ color: 'var(--ink-muted)', padding: 20 }}>Computing profile…</div>}
            </div>
          )}
        </div>
      </div>

      {wizardOpen && (
        <DxfWizard
          onClose={() => setWizardOpen(false)}
          onGeoreferenced={(r) => { setGeoref(r); setShowOverlay(true); }}
        />
      )}
    </div>
  );
}
