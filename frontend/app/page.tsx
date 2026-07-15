'use client';

/**
 * Main screen: sidebar (link parameters + DXF import + radio studies +
 * indoor studio), Leaflet map (TX/RX placement, DXF footprint + hillshade,
 * coverage raster) and the provenance-colored elevation profile chart.
 *
 * Ergonomics per the multi-persona review:
 * - TX/RX are typeable (exact lat/lon), swappable, or set from device GPS
 * - a search box jumps to "lat, lon" or a geocoded place name
 * - the whole session (endpoints, params, DXF binding, tiles URL) persists
 *   to localStorage and is restored after a reload
 * - profile recomputes are debounced; number fields tolerate being emptied
 */
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useCallback, useEffect, useRef, useState } from 'react';
import AuthPanel from '@/components/AuthPanel';
import BatchPanel from '@/components/BatchPanel';
import DxfWizard from '@/components/DxfWizard';
import Help from '@/components/Help';
import IndoorStudio from '@/components/IndoorStudio';
import ProfileChart from '@/components/ProfileChart';
import StudyPanel from '@/components/StudyPanel';
import { fetchDxfState, fetchProfile, fetchSurfaceAvailable, profileCsvUrl } from '@/lib/api';
import {
  authHeaders, createProject, fetchMe, setToken, type User,
} from '@/lib/saas';
import type { FlyTarget } from '@/components/MapView';
import type {
  CoverageResponse, GeorefResponse, LatLng, ProfileResponse,
} from '@/lib/types';

const MapView = dynamic(() => import('@/components/MapView'), {
  ssr: false,
  loading: () => <div style={{ padding: 20, color: 'var(--ink-muted)' }}>Loading map…</div>,
});

const STORE_KEY = 'am_session_v1';

function num(s: string, fallback: number): number {
  const v = parseFloat(s);
  return Number.isFinite(v) ? v : fallback;
}

export default function Home() {
  const [tx, setTx] = useState<LatLng | null>(null);
  const [rx, setRx] = useState<LatLng | null>(null);
  const [placing, setPlacing] = useState<'tx' | 'rx' | null>('tx');

  // Numeric fields keep their raw string so clearing mid-edit never snaps
  // to a bogus value; they are parsed (with defaults) at fetch time.
  const [txHeight, setTxHeight] = useState('20');
  const [rxHeight, setRxHeight] = useState('10');
  const [freqMhz, setFreqMhz] = useState('446');

  const [wizardOpen, setWizardOpen] = useState(false);
  const [indoorOpen, setIndoorOpen] = useState(false);
  const [georef, setGeoref] = useState<GeorefResponse | null>(null);
  const [showOverlay, setShowOverlay] = useState(true);

  const [technology, setTechnology] = useState<string | null>(null);
  const [model, setModel] = useState<string | null>(null);
  const [environment, setEnvironment] = useState<string | null>(null);
  const [foliageDepth, setFoliageDepth] = useState(0);
  const [rainRate, setRainRate] = useState(0);
  const [clutterPct, setClutterPct] = useState(0);
  const [surfaceOn, setSurfaceOn] = useState(false);
  const [surfaceAvailable, setSurfaceAvailable] = useState(false);
  const [coverage, setCoverage] = useState<CoverageResponse | null>(null);

  const [profile, setProfile] = useState<ProfileResponse | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [search, setSearch] = useState('');
  const [flyTarget, setFlyTarget] = useState<FlyTarget | null>(null);
  const [customTileUrl, setCustomTileUrl] = useState('');
  const [restored, setRestored] = useState(false);
  const [theme, setTheme] = useState<'auto' | 'light' | 'dark'>('auto');
  const [user, setUser] = useState<User | null>(null);
  const [authOpen, setAuthOpen] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const flySeq = useRef(1);

  // Account state + deep-linked project loading (?project=<id>).
  useEffect(() => {
    fetchMe().then(setUser).catch(() => {});
    const params = new URLSearchParams(window.location.search);
    const sharedToken = params.get('shared');
    if (sharedToken) {
      // Public read-only project link: no auth required, served by the
      // token endpoint that strips owner/token fields.
      fetch(`/api/projects/shared/${sharedToken}`)
        .then(async (r) => {
          if (r.ok) {
            const body = await r.json();
            if (body?.project?.data) {
              localStorage.setItem(STORE_KEY, JSON.stringify(body.project.data));
              window.location.replace('/');
            }
          } else {
            setSaveMsg('This shared link is invalid or has been revoked.');
          }
        }).catch(() => setSaveMsg('Could not load the shared project.'));
      return;
    }
    const pid = params.get('project');
    if (pid) {
      fetch(`/api/projects/${pid}`, { headers: authHeaders() })
        .then(async (r) => {
          if (r.ok) {
            const body = await r.json();
            if (body?.project?.data) {
              localStorage.setItem(STORE_KEY, JSON.stringify(body.project.data));
              window.location.replace('/');   // reload cleanly with the session
            }
          } else if (r.status === 401) {
            setAuthOpen(true);                 // must sign in to open a project
            setSaveMsg('Sign in to open this shared project link.');
          }
        }).catch(() => {});
    }
  }, []);

  async function saveAsProject() {
    if (!user) { setAuthOpen(true); return; }
    const name = window.prompt('Project name:',
      `Study ${new Date().toLocaleDateString()}`);
    if (!name) return;
    try {
      const raw = localStorage.getItem(STORE_KEY);
      await createProject(name, raw ? JSON.parse(raw) : {});
      setSaveMsg(`Saved “${name}” — manage it in the Command Center.`);
      setTimeout(() => setSaveMsg(null), 5000);
    } catch (e) {
      setSaveMsg((e as Error).message);
      setTimeout(() => setSaveMsg(null), 8000);
    }
  }

  // Theme: 'auto' follows the OS; explicit choice stamps <html data-theme>.
  useEffect(() => {
    const saved = localStorage.getItem('am_theme');
    if (saved === 'light' || saved === 'dark') setTheme(saved);
  }, []);

  // Surface-model (DSM) availability: shows the DSM toggle only when the
  // backend has AM_DSM_URL configured.
  useEffect(() => { fetchSurfaceAvailable().then(setSurfaceAvailable); }, []);

  // Drop a stale coverage raster when the inputs that produced it change
  // (TX position or technology): keeping it painted invites the classic
  // "screenshot the wrong map" mistake.  Skips the first render so a
  // restored session keeps any coverage the user re-runs.
  const coverageDeps = useRef(false);
  useEffect(() => {
    if (!coverageDeps.current) { coverageDeps.current = true; return; }
    setCoverage(null);
  }, [tx?.lat, tx?.lng, technology]);
  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'auto') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', theme);
    try { localStorage.setItem('am_theme', theme); } catch { /* ignore */ }
  }, [theme]);

  // ------------------------------------------------ session persistence
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (raw) {
        const s = JSON.parse(raw);
        if (s.tx) { setTx(s.tx); setPlacing(s.rx ? null : 'rx'); }
        if (s.rx) setRx(s.rx);
        if (s.txHeight) setTxHeight(String(s.txHeight));
        if (s.rxHeight) setRxHeight(String(s.rxHeight));
        if (s.freqMhz) setFreqMhz(String(s.freqMhz));
        if (s.technology) setTechnology(s.technology);
        if (s.model) setModel(s.model);
        if (s.environment) setEnvironment(s.environment);
        if (typeof s.foliageDepth === 'number') setFoliageDepth(s.foliageDepth);
        if (typeof s.rainRate === 'number') setRainRate(s.rainRate);
        if (typeof s.clutterPct === 'number') setClutterPct(s.clutterPct);
        if (typeof s.surfaceOn === 'boolean') setSurfaceOn(s.surfaceOn);
        if (s.customTileUrl) setCustomTileUrl(s.customTileUrl);
        // Rebind a georeferenced DXF (server rebuilds its grid on demand).
        if (s.dxfId) {
          fetchDxfState(s.dxfId).then(setGeoref).catch(() => {});
        }
      }
    } catch { /* corrupted storage: start fresh */ }
    setRestored(true);
  }, []);

  useEffect(() => {
    if (!restored) return;
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({
        tx, rx, txHeight, rxHeight, freqMhz,
        technology, model, environment, customTileUrl,
        foliageDepth, rainRate, clutterPct, surfaceOn,
        dxfId: georef?.dxf_id ?? null,
      }));
    } catch { /* storage full/unavailable */ }
  }, [restored, tx, rx, txHeight, rxHeight, freqMhz, technology, model,
      environment, customTileUrl, foliageDepth, rainRate, clutterPct,
      surfaceOn, georef]);

  // --------------------------------------------------------- placement
  const handlePlace = useCallback((p: LatLng) => {
    if (placing === 'tx') {
      setTx(p);
      setPlacing('rx');
    } else if (placing === 'rx') {
      setRx(p);
      setPlacing(null);
    }
  }, [placing]);

  // Coordinate fields hold raw strings while editing (no toFixed snapping
  // mid-keystroke); they sync FROM tx/rx whenever the map/GPS changes them.
  const [coordDraft, setCoordDraft] = useState({ txLat: '', txLng: '', rxLat: '', rxLng: '' });
  useEffect(() => {
    setCoordDraft((d) => ({ ...d,
      txLat: tx ? tx.lat.toFixed(5) : '', txLng: tx ? tx.lng.toFixed(5) : '' }));
  }, [tx]);
  useEffect(() => {
    setCoordDraft((d) => ({ ...d,
      rxLat: rx ? rx.lat.toFixed(5) : '', rxLng: rx ? rx.lng.toFixed(5) : '' }));
  }, [rx]);

  function editCoord(field: keyof typeof coordDraft, value: string) {
    const nextDraft = { ...coordDraft, [field]: value };
    setCoordDraft(nextDraft);
    const which = field.startsWith('tx') ? 'tx' : 'rx';
    // Only commit a point once BOTH axes of that endpoint parse finite, so
    // typing one coordinate before the other exists can't drop a pin at
    // longitude 0 (off the coast of nowhere) and fire a bogus fetch.
    const latV = parseFloat(which === 'tx' ? nextDraft.txLat : nextDraft.rxLat);
    const lngV = parseFloat(which === 'tx' ? nextDraft.txLng : nextDraft.rxLng);
    if (!Number.isFinite(latV) || !Number.isFinite(lngV)) return;
    (which === 'tx' ? setTx : setRx)({ lat: latV, lng: lngV });
  }

  function swapEnds() {
    setTx(rx);
    setRx(tx);
    setTxHeight(rxHeight);
    setRxHeight(txHeight);
  }

  function useMyLocation() {
    if (!navigator.geolocation) {
      setSaveMsg('This device does not expose GPS/geolocation.');
      return;
    }
    navigator.geolocation.getCurrentPosition((pos) => {
      const p = { lat: pos.coords.latitude, lng: pos.coords.longitude };
      if (placing === 'rx') setRx(p); else { setTx(p); setPlacing('rx'); }
      setFlyTarget({ ...p, zoom: 14, seq: flySeq.current++ });
    }, (err) => {
      setSaveMsg(`GPS unavailable: ${err.message}`);
      setTimeout(() => setSaveMsg(null), 8000);
    });
  }

  // ------------------------------------------------------------ search
  async function runSearch() {
    const q = search.trim();
    if (!q) return;
    // "lat, lon" (or "lat lon") jumps directly.
    const m = q.match(/^(-?\d+(?:\.\d+)?)[,;\s]+(-?\d+(?:\.\d+)?)$/);
    if (m) {
      setFlyTarget({ lat: parseFloat(m[1]), lng: parseFloat(m[2]),
                     zoom: 14, seq: flySeq.current++ });
      return;
    }
    // Otherwise geocode via Nominatim (graceful failure offline).
    try {
      const resp = await fetch(
        `https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(q)}`);
      const hits = await resp.json();
      if (hits?.[0]) {
        setFlyTarget({ lat: parseFloat(hits[0].lat), lng: parseFloat(hits[0].lon),
                       zoom: 13, seq: flySeq.current++ });
      } else {
        setSaveMsg(`No results for “${q}”.`);
        setTimeout(() => setSaveMsg(null), 5000);
      }
    } catch {
      setSaveMsg('Search needs internet (offline). Type “lat, lon” to jump directly.');
      setTimeout(() => setSaveMsg(null), 6000);
    }
  }

  // ---------------------------------------------- profile (debounced)
  useEffect(() => {
    if (!tx || !rx) return;
    let cancelled = false;
    setLoading(true);
    setProfileError(null);
    const timer = setTimeout(() => {
      fetchProfile({
        lat1: tx.lat, lon1: tx.lng, lat2: rx.lat, lon2: rx.lng,
        dxfId: georef?.dxf_id ?? null,
        txHeight: num(txHeight, 20), rxHeight: num(rxHeight, 10),
        freqMhz: num(freqMhz, 446),
        technology, model, environment,
        foliageDepthM: foliageDepth, rainRateMmH: rainRate,
        clutterPct, surface: surfaceOn,
      })
        .then((p) => { if (!cancelled) setProfile(p); })
        .catch((e) => { if (!cancelled) setProfileError((e as Error).message); })
        .finally(() => { if (!cancelled) setLoading(false); });
    }, 350);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [tx, rx, txHeight, rxHeight, freqMhz, georef, technology, model, environment,
      foliageDepth, rainRate, clutterPct, surfaceOn]);

  const validation = georef?.validation;
  const transform = georef?.transform;
  const endA = profile?.points[0];
  const endB = profile?.points[profile.points.length - 1];
  const worst = profile && profile.rf.worst_obstruction_v > -0.78
    ? profile.points[profile.rf.worst_obstruction_index] : null;

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>AntennaMaster</h1>
        <nav style={{ display: 'flex', gap: 6 }}>
          <Link href="/" className="nav-link on">Planner</Link>
          <Link href="/dashboard" className="nav-link">Command Center</Link>
          <Link href="/field" className="nav-link">Tactical</Link>
          <Link href="/pitch" className="nav-link">Pitch</Link>
        </nav>
        <div className="header-search">
          <input
            placeholder="Search place or “lat, lon”…"
            value={search}
            aria-label="Search place or coordinates"
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && runSearch()}
          />
          <button onClick={runSearch}>Go</button>
          <button
            aria-label="Toggle color theme"
            title={`Theme: ${theme}`}
            onClick={() => setTheme(theme === 'auto' ? 'dark' : theme === 'dark' ? 'light' : 'auto')}
          >
            {theme === 'dark' ? '🌙' : theme === 'light' ? '☀️' : '🌗'}
          </button>
          <button onClick={saveAsProject} title="Save this study as a project">
            💾 Save
          </button>
          {user ? (
            <span className="user-chip">
              {user.name || user.email}
              <span className="tier-badge">{user.tier}</span>
              <button onClick={() => { setToken(null); setUser(null); }}>Sign out</button>
            </span>
          ) : (
            <button className="primary" onClick={() => setAuthOpen(true)}>Sign in</button>
          )}
        </div>
      </header>
      {saveMsg && (
        <div style={{ padding: '4px 16px', fontSize: 12, background: 'var(--accent-soft)',
                      color: 'var(--accent-soft-ink)' }}>{saveMsg}</div>
      )}

      <div className="app-main">
        <aside className="sidebar">
          <div className="panel">
            <h3>Link endpoints</h3>
            <div className="row">
              <button className={placing === 'tx' ? 'primary' : ''} onClick={() => setPlacing('tx')}>
                {tx ? '↺ Move TX' : 'Place TX'}
              </button>
              <button className={placing === 'rx' ? 'primary' : ''} onClick={() => setPlacing('rx')}>
                {rx ? '↺ Move RX' : 'Place RX'}
              </button>
              <button onClick={swapEnds} disabled={!tx || !rx} title="Swap TX and RX ends"
                aria-label="Swap TX and RX">⇄</button>
            </div>
            <div className="row">
              <button onClick={useMyLocation} style={{ width: '100%' }}>
                📍 Use my GPS position
              </button>
            </div>
            {/* Exact coordinates: type or paste from a site database / GPS. */}
            <div className="row">
              <div>
                <label>TX lat</label>
                <input type="number" step="0.00001" value={coordDraft.txLat}
                  onChange={(e) => editCoord('txLat', e.target.value)} />
              </div>
              <div>
                <label>TX lon</label>
                <input type="number" step="0.00001" value={coordDraft.txLng}
                  onChange={(e) => editCoord('txLng', e.target.value)} />
              </div>
            </div>
            <div className="row">
              <div>
                <label>RX lat</label>
                <input type="number" step="0.00001" value={coordDraft.rxLat}
                  onChange={(e) => editCoord('rxLat', e.target.value)} />
              </div>
              <div>
                <label>RX lon</label>
                <input type="number" step="0.00001" value={coordDraft.rxLng}
                  onChange={(e) => editCoord('rxLng', e.target.value)} />
              </div>
            </div>
            {endA && endB && (
              <>
                <div className="stat-line"><span className="k">TX ground</span><span className="v">{endA.elev.toFixed(1)} m ASL</span></div>
                <div className="stat-line"><span className="k">RX ground</span><span className="v">{endB.elev.toFixed(1)} m ASL</span></div>
              </>
            )}
            <div className="row" style={{ marginTop: 8 }}>
              <div>
                <label>TX height (m)</label>
                <input type="number" min={0} value={txHeight}
                  onChange={(e) => setTxHeight(e.target.value)} />
              </div>
              <div>
                <label>RX height (m)</label>
                <input type="number" min={0} value={rxHeight}
                  onChange={(e) => setRxHeight(e.target.value)} />
              </div>
            </div>
            <div>
              <label>Frequency (MHz) — terrain analysis<Help term="fspl" /></label>
              <input type="number" min={1} value={freqMhz}
                onChange={(e) => setFreqMhz(e.target.value)} />
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
                {typeof transform.rms_residual_m === 'number' && (
                  <div className="stat-line">
                    <span className="k">Helmert RMS residual<Help term="helmert" /></span>
                    <span className="v" style={{ color: transform.rms_residual_m > 10 ? 'var(--status-critical)' : 'var(--status-good)' }}>
                      {transform.rms_residual_m.toFixed(2)} m
                    </span>
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

          <StudyPanel
            tx={tx} dxfId={georef?.dxf_id ?? null} txHeight={num(txHeight, 20)}
            technology={technology} onTechnologyChange={setTechnology}
            model={model} onModelChange={setModel}
            environment={environment} onEnvironmentChange={setEnvironment}
            foliageDepth={foliageDepth} onFoliageChange={setFoliageDepth}
            rainRate={rainRate} onRainChange={setRainRate}
            clutterPct={clutterPct} onClutterChange={setClutterPct}
            surfaceOn={surfaceOn} onSurfaceChange={setSurfaceOn}
            surfaceAvailable={surfaceAvailable}
            study={profile?.study ?? null}
            coverage={coverage} onCoverage={setCoverage}
          />

          <BatchPanel
            tx={tx} technology={technology} dxfId={georef?.dxf_id ?? null}
            foliageDepth={foliageDepth} rainRate={rainRate}
            clutterPct={clutterPct} surfaceOn={surfaceOn}
            onFocusReceiver={(lat, lon) => {
              setRx({ lat, lng: lon });
              setFlyTarget({ lat, lng: lon, zoom: 14, seq: flySeq.current++ });
            }}
          />

          <div className="panel">
            <h3>Indoor &amp; underground</h3>
            <p className="hint">
              Floor-plan Wi-Fi/DAS coverage (DXF walls + materials), tunnel/mine
              waveguide links and through-the-earth studies — no map needed.
            </p>
            <button style={{ width: '100%' }} onClick={() => setIndoorOpen(true)}>
              Open indoor / underground studio…
            </button>
          </div>

          {validation?.warning && (
            <div className="warning-box">
              <b>⚠ Terrain validation warning</b><br />
              {validation.warning}
            </div>
          )}
          {validation?.error && (
            <div className="warning-box"><b>⚠</b> {validation.error}</div>
          )}

          {profile && tx && rx && (
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
              <div className="stat-line"><span className="k">F1 clearance<Help term="fresnel" /></span><span className="v">{(profile.rf.fresnel_clearance_ratio * 100).toFixed(0)}%</span></div>
              {worst && (
                <div className="stat-line">
                  <span className="k">Worst obstruction</span>
                  <span className="v">{(worst.d / 1000).toFixed(2)} km (ν={profile.rf.worst_obstruction_v.toFixed(2)})</span>
                </div>
              )}
              <div className="stat-line"><span className="k">k-factor<Help term="kfactor" /></span><span className="v">{profile.rf.k_factor.toFixed(2)}</span></div>
              <a
                className="download-link"
                href={profileCsvUrl({
                  lat1: tx.lat, lon1: tx.lng, lat2: rx.lat, lon2: rx.lng,
                  dxfId: georef?.dxf_id ?? null,
                  txHeight: num(txHeight, 20), rxHeight: num(rxHeight, 10),
                  freqMhz: num(freqMhz, 446), technology, model, environment,
                  foliageDepthM: foliageDepth, rainRateMmH: rainRate,
                  clutterPct, surface: surfaceOn,
                })}
                download
              >
                ⤓ Download profile CSV
              </a>
              <div style={{ marginTop: 6, fontSize: 11 }}>
                <span className="badge srtm">SRTM</span>{' '}
                <span className="badge dxf">DXF</span>{' '}
                <span style={{ color: 'var(--ink-muted)' }}>= data provenance in the chart</span>
              </div>
            </div>
          )}
          {profileError && <div className="error-box">{profileError}</div>}

          <div className="panel">
            <h3>Map provider</h3>
            <label>Custom XYZ tile URL (optional)</label>
            <input
              placeholder="https://tiles.example.com/{z}/{x}/{y}.png"
              value={customTileUrl}
              onChange={(e) => setCustomTileUrl(e.target.value)}
            />
            <p className="hint">Appears as “Custom provider” in the map’s layer switcher.
              Built-ins: OSM, OpenTopoMap, Carto, Esri.</p>
          </div>
        </aside>

        <div className="map-and-chart">
          <div className="map-wrap">
            <MapView
              tx={tx} rx={rx} placing={placing} onPlace={handlePlace}
              georef={georef} showOverlay={showOverlay}
              coverage={coverage}
              customTileUrl={customTileUrl.includes('{z}') ? customTileUrl : undefined}
              flyTarget={flyTarget}
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
      {indoorOpen && <IndoorStudio onClose={() => setIndoorOpen(false)} />}
      {authOpen && <AuthPanel onClose={() => setAuthOpen(false)} onUser={setUser} />}
    </div>
  );
}
