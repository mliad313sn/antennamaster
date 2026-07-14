'use client';

/**
 * Indoor & Underground studio — three study types no DEM can cover:
 *
 * 1. Floor plan / mine gallery coverage: upload a DXF whose layers are
 *    interpreted as WALLS (not relief), assign a material per layer, click
 *    the plan to place the TX, and run a COST-231 multi-wall heatmap.
 * 2. Tunnel link: Emslie waveguide model — RX power vs distance chart.
 * 3. Through-the-earth: VLF induction link through conductive ground.
 */
import { useEffect, useRef, useState } from 'react';
import {
  Area, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts';
import {
  fetchMaterials, fetchPlanPreview, fetchTteStudy, fetchTunnelStudy,
  fetchUndergroundPresets, simulateIndoorCoverage, uploadDxf,
} from '@/lib/api';
import type {
  IndoorCoverageResponse, Material, TteResponse, TunnelResponse,
  UndergroundPresets, UploadResponse,
} from '@/lib/types';

type Tab = 'plan' | 'tunnel' | 'tte';

export default function IndoorStudio({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<Tab>('plan');
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" style={{ width: 860 }} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>Indoor &amp; underground studies</h2>
          <button onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <div className="mode-tabs">
            <button className={tab === 'plan' ? 'active' : ''} onClick={() => setTab('plan')}>
              Floor plan / mine coverage
            </button>
            <button className={tab === 'tunnel' ? 'active' : ''} onClick={() => setTab('tunnel')}>
              Tunnel link
            </button>
            <button className={tab === 'tte' ? 'active' : ''} onClick={() => setTab('tte')}>
              Through-the-earth
            </button>
          </div>
          {tab === 'plan' && <PlanStudy />}
          {tab === 'tunnel' && <TunnelStudy />}
          {tab === 'tte' && <TteStudy />}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- plan tab
function PlanStudy() {
  const [upload, setUpload] = useState<UploadResponse | null>(null);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [layerMats, setLayerMats] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<{ url: string; bounds: [number, number, number, number] } | null>(null);
  const [tx, setTx] = useState<{ x: number; y: number } | null>(null);
  const [unitScale, setUnitScale] = useState(1.0);
  const [freqMhz, setFreqMhz] = useState(2442);
  const [txPower, setTxPower] = useState(20);
  const [sensitivity, setSensitivity] = useState(-82);
  const [result, setResult] = useState<IndoorCoverageResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);

  useEffect(() => { fetchMaterials().then(setMaterials).catch(() => {}); }, []);

  async function handleFile(file: File) {
    setBusy(true); setError(null); setResult(null); setPreview(null); setTx(null);
    try {
      const up = await uploadDxf(file);
      setUpload(up);
      // Default materials guessed from layer names; 'none' for empty layers.
      const defaults: Record<string, string> = {};
      for (const l of up.layers) {
        defaults[l.name] = l.entity_count > 0 ? guessMat(l.name) : 'none';
      }
      setLayerMats(defaults);
      await refreshPreview(up.dxf_id, defaults);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  function guessMat(name: string): string {
    const n = name.toLowerCase();
    if (/(concrete|beton)/.test(n)) return 'concrete';
    if (/(glass|window|fenetre)/.test(n)) return 'glass';
    if (/(metal|steel)/.test(n)) return 'metal';
    if (/(rock|pillar|mine)/.test(n)) return 'rock';
    if (/(door|porte|wood)/.test(n)) return 'wood';
    if (/(wall|mur|masonry|brick)/.test(n)) return 'brick';
    return 'drywall';
  }

  async function refreshPreview(dxfId: string, mats: Record<string, string>) {
    const active = Object.entries(mats).filter(([, m]) => m !== 'none').map(([l]) => l);
    if (!active.length) { setPreview(null); return; }
    try {
      setPreview(await fetchPlanPreview(dxfId, active));
    } catch (e) { setError((e as Error).message); }
  }

  function planClick(e: React.MouseEvent<HTMLImageElement>) {
    if (!preview || !imgRef.current) return;
    const rect = imgRef.current.getBoundingClientRect();
    const [x0, y0, x1, y1] = preview.bounds;
    const fx = (e.clientX - rect.left) / rect.width;
    const fy = (e.clientY - rect.top) / rect.height;
    setTx({ x: x0 + fx * (x1 - x0), y: y1 - fy * (y1 - y0) }); // image y is flipped
    setResult(null);
  }

  async function run() {
    if (!upload || !tx) return;
    setBusy(true); setError(null);
    try {
      setResult(await simulateIndoorCoverage({
        dxfId: upload.dxf_id, layerMaterials: layerMats,
        txX: tx.x, txY: tx.y, unitScale,
        freqMhz, txPowerDbm: txPower, rxSensitivityDbm: sensitivity,
      }));
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <div>
      {!upload && (
        <>
          <p className="hint">
            Upload a DXF floor plan, metro station or mine gallery layout. LINE /
            POLYLINE / ARC entities become walls; assign a material to each layer,
            click the plan to place the transmitter, then run the multi-wall
            coverage simulation. No georeferencing needed — everything runs in
            drawing coordinates.
          </p>
          <input type="file" accept=".dxf"
            onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])} />
          {busy && <p className="hint">Parsing…</p>}
        </>
      )}

      {upload && (
        <div style={{ display: 'flex', gap: 14 }}>
          <div style={{ width: 260, flexShrink: 0 }}>
            <h3 style={{ margin: '0 0 6px', fontSize: 13 }}>Layer materials</h3>
            <div style={{ maxHeight: 220, overflowY: 'auto' }}>
              {upload.layers.filter((l) => l.entity_count > 0).map((l) => (
                <div key={l.name} style={{ marginBottom: 6 }}>
                  <label>{l.name} ({l.entity_count})</label>
                  <select value={layerMats[l.name] ?? 'none'}
                    onChange={(e) => {
                      const next = { ...layerMats, [l.name]: e.target.value };
                      setLayerMats(next);
                      refreshPreview(upload.dxf_id, next);
                      setResult(null);
                    }}>
                    {materials.map((m) => (
                      <option key={m.key} value={m.key}>{m.label}</option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
            <div className="row" style={{ marginTop: 8 }}>
              <div>
                <label>Units</label>
                <select value={unitScale} onChange={(e) => setUnitScale(parseFloat(e.target.value))}>
                  <option value={1}>Meters</option>
                  <option value={0.3048}>Feet</option>
                  <option value={0.01}>Centimeters</option>
                  <option value={0.001}>Millimeters</option>
                </select>
              </div>
              <div>
                <label>Freq (MHz)</label>
                <input type="number" value={freqMhz}
                  onChange={(e) => setFreqMhz(parseFloat(e.target.value) || 2442)} />
              </div>
            </div>
            <div className="row">
              <div>
                <label>TX power (dBm)</label>
                <input type="number" value={txPower}
                  onChange={(e) => setTxPower(parseFloat(e.target.value) || 20)} />
              </div>
              <div>
                <label>Sensitivity (dBm)</label>
                <input type="number" value={sensitivity}
                  onChange={(e) => setSensitivity(parseFloat(e.target.value) || -82)} />
              </div>
            </div>
            <button className="primary" style={{ width: '100%', marginTop: 6 }}
              disabled={!tx || busy} onClick={run}>
              {busy ? 'Simulating…' : tx ? 'Run coverage' : 'Click the plan to place TX'}
            </button>
            {result && (
              <>
                <div className="stat-line" style={{ marginTop: 8 }}>
                  <span className="k">Served area</span>
                  <span className="v">{(result.stats.served_area_fraction * 100).toFixed(0)}%</span>
                </div>
                <div className="stat-line"><span className="k">Walls</span><span className="v">{result.stats.walls}</span></div>
                <div style={{ marginTop: 4 }}>
                  {result.legend.map((l) => (
                    <div key={l.label} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
                      <span style={{ width: 12, height: 12, borderRadius: 3, background: l.color }} />
                      <span style={{ color: 'var(--ink-secondary)' }}>{l.label}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            {result ? (
              /* Heatmap replaces the preview; click returns to TX placement */
              // eslint-disable-next-line @next/next/no-img-element
              <img src={result.png_url} alt="Indoor coverage heatmap"
                style={{ width: '100%', border: '1px solid var(--hairline)', borderRadius: 8, cursor: 'crosshair' }}
                ref={imgRef} onClick={planClick} />
            ) : preview ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={preview.url} alt="Floor plan preview"
                style={{ width: '100%', border: '1px solid var(--hairline)', borderRadius: 8, cursor: 'crosshair' }}
                ref={imgRef} onClick={planClick} />
            ) : (
              <p className="hint">No structural layers selected.</p>
            )}
            {tx && !result && (
              <p className="hint">TX at ({tx.x.toFixed(1)}, {tx.y.toFixed(1)}) drawing units — run the simulation.</p>
            )}
          </div>
        </div>
      )}
      {error && <div className="error-box">{error}</div>}
    </div>
  );
}

// -------------------------------------------------------------- tunnel tab
function TunnelStudy() {
  const [presets, setPresets] = useState<UndergroundPresets | null>(null);
  const [freq, setFreq] = useState(450);
  const [width, setWidth] = useState(4);
  const [height, setHeight] = useState(3);
  const [length, setLength] = useState(3000);
  const [wall, setWall] = useState('rock');
  const [txPower, setTxPower] = useState(37);
  const [txGain, setTxGain] = useState(6);
  const [sensitivity, setSensitivity] = useState(-110);
  const [result, setResult] = useState<TunnelResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { fetchUndergroundPresets().then(setPresets).catch(() => {}); }, []);

  async function run() {
    setBusy(true); setError(null);
    try {
      setResult(await fetchTunnelStudy({
        freqMhz: freq, widthM: width, heightM: height, lengthM: length,
        wall, txPowerDbm: txPower, txGainDbi: txGain, rxSensitivityDbm: sensitivity,
      }));
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <div>
      <p className="hint">
        Waveguide-regime propagation in a tunnel or mine gallery (Emslie model):
        free space up to the modal breakpoint, then linear dB/m attenuation.
        Higher frequencies travel farther — the opposite of open terrain.
      </p>
      <div className="row">
        <div><label>Frequency (MHz)</label><input type="number" value={freq} onChange={(e) => setFreq(parseFloat(e.target.value) || 450)} /></div>
        <div><label>Width (m)</label><input type="number" value={width} onChange={(e) => setWidth(parseFloat(e.target.value) || 4)} /></div>
        <div><label>Height (m)</label><input type="number" value={height} onChange={(e) => setHeight(parseFloat(e.target.value) || 3)} /></div>
        <div><label>Length (m)</label><input type="number" value={length} onChange={(e) => setLength(parseFloat(e.target.value) || 3000)} /></div>
      </div>
      <div className="row">
        <div>
          <label>Wall material</label>
          <select value={wall} onChange={(e) => setWall(e.target.value)}>
            {(presets?.tunnel_walls ?? []).map((w) => (
              <option key={w.key} value={w.key}>{w.label} (εr {w.eps_r})</option>
            ))}
          </select>
        </div>
        <div><label>TX power (dBm)</label><input type="number" value={txPower} onChange={(e) => setTxPower(parseFloat(e.target.value) || 37)} /></div>
        <div><label>TX gain (dBi)</label><input type="number" value={txGain} onChange={(e) => setTxGain(parseFloat(e.target.value) || 6)} /></div>
        <div><label>Sensitivity (dBm)</label><input type="number" value={sensitivity} onChange={(e) => setSensitivity(parseFloat(e.target.value) || -110)} /></div>
      </div>
      <button className="primary" disabled={busy} onClick={run}>
        {busy ? 'Computing…' : 'Compute tunnel link'}
      </button>
      {result && (
        <>
          <div className="row" style={{ marginTop: 10 }}>
            <div className="stat-line"><span className="k">Attenuation</span><span className="v">{result.alpha_db_per_m.toFixed(3)} dB/m</span></div>
            <div className="stat-line"><span className="k">Breakpoint</span><span className="v">{result.breakpoint_m.toFixed(0)} m</span></div>
            <div className="stat-line"><span className="k">Max range</span><span className="v">{result.max_range_m.toFixed(0)} m</span></div>
          </div>
          <div style={{ height: 240 }}>
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={result.points} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
                <XAxis dataKey="d" type="number" domain={['dataMin', 'dataMax']}
                  tick={{ fontSize: 11, fill: 'var(--ink-muted)' }} stroke="var(--baseline)"
                  label={{ value: 'm', position: 'insideBottomRight', offset: -2, fontSize: 11, fill: 'var(--ink-muted)' }} />
                <YAxis width={52} tick={{ fontSize: 11, fill: 'var(--ink-muted)' }} stroke="var(--baseline)"
                  label={{ value: 'dBm', position: 'insideTopLeft', offset: 4, fontSize: 11, fill: 'var(--ink-muted)' }} />
                <Tooltip formatter={(v: number) => [`${Number(v).toFixed(1)} dBm`, 'RX power']}
                  labelFormatter={(l) => `${l} m`} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Area dataKey="rx_power_dbm" name="RX power" stroke="#2a78d6"
                  fill="#2a78d6" fillOpacity={0.3} strokeWidth={2} dot={false}
                  isAnimationActive={false} />
                <ReferenceLine y={sensitivity} stroke="var(--status-critical)"
                  strokeDasharray="6 4"
                  label={{ value: 'sensitivity', fontSize: 11, fill: 'var(--status-critical)', position: 'insideBottomLeft' }} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
      {error && <div className="error-box">{error}</div>}
    </div>
  );
}

// ----------------------------------------------------------------- TTE tab
function TteStudy() {
  const [presets, setPresets] = useState<UndergroundPresets | null>(null);
  const [freqHz, setFreqHz] = useState(5000);
  const [depth, setDepth] = useState(100);
  const [earth, setEarth] = useState('average_soil');
  const [txPower, setTxPower] = useState(30);
  const [sensitivity, setSensitivity] = useState(-130);
  const [result, setResult] = useState<TteResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { fetchUndergroundPresets().then(setPresets).catch(() => {}); }, []);

  async function run() {
    setBusy(true); setError(null);
    try {
      setResult(await fetchTteStudy({
        freqHz, depthM: depth, earth, txPowerDbm: txPower,
        rxSensitivityDbm: sensitivity,
      }));
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <div>
      <p className="hint">
        Through-the-earth link (mine paging / cave rescue): a VLF magnetic loop
        couples through conductive ground. Loss = skin-depth attenuation +
        near-field (1/r³) spreading — which is why only very low frequencies
        get through.
      </p>
      <div className="row">
        <div><label>Frequency (Hz)</label><input type="number" value={freqHz} onChange={(e) => setFreqHz(parseFloat(e.target.value) || 5000)} /></div>
        <div><label>Depth (m)</label><input type="number" value={depth} onChange={(e) => setDepth(parseFloat(e.target.value) || 100)} /></div>
        <div>
          <label>Ground</label>
          <select value={earth} onChange={(e) => setEarth(e.target.value)}>
            {(presets?.earth ?? []).map((g) => (
              <option key={g.key} value={g.key}>{g.label} ({g.sigma} S/m)</option>
            ))}
          </select>
        </div>
      </div>
      <div className="row">
        <div><label>TX power (dBm)</label><input type="number" value={txPower} onChange={(e) => setTxPower(parseFloat(e.target.value) || 30)} /></div>
        <div><label>Sensitivity (dBm)</label><input type="number" value={sensitivity} onChange={(e) => setSensitivity(parseFloat(e.target.value) || -130)} /></div>
      </div>
      <button className="primary" disabled={busy} onClick={run}>
        {busy ? 'Computing…' : 'Compute TTE link'}
      </button>
      {result && (
        <div style={{ marginTop: 10 }}>
          <div className="stat-line"><span className="k">Skin depth</span><span className="v">{result.skin_depth_m.toFixed(1)} m</span></div>
          <div className="stat-line"><span className="k">Ground attenuation</span><span className="v">{result.attenuation_db.toFixed(1)} dB</span></div>
          <div className="stat-line"><span className="k">Near-field spreading</span><span className="v">{result.spreading_db.toFixed(1)} dB</span></div>
          <div className="stat-line"><span className="k">RX power</span><span className="v">{result.rx_power_dbm.toFixed(1)} dBm</span></div>
          <div className="stat-line">
            <span className="k">Margin</span>
            <span className="v" style={{ color: result.served ? 'var(--status-good)' : 'var(--status-critical)' }}>
              {result.margin_db.toFixed(1)} dB {result.served ? '(link works)' : '(no link)'}
            </span>
          </div>
        </div>
      )}
      {error && <div className="error-box">{error}</div>}
    </div>
  );
}
