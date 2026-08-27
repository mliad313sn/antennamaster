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
import { useEffect, useRef, useState, useId } from 'react';
import { useTranslation } from 'react-i18next';
import { useDialog } from '@/lib/useDialog';
import { downloadAsset, useAuthedAsset } from '@/lib/authedAsset';
import {
  Area, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts';
import {
  dasSolve, fetchEquipment, fetchMaterials, fetchPlanPreview, fetchTteStudy,
  fetchTunnelStudy, fetchUndergroundPresets, indoorStack, leakyFeederStudy,
  simulateIndoorCoverage, uploadDxf,
} from '@/lib/api';
import type {
  Equipment, IndoorCoverageResponse, Material, TteResponse, TunnelResponse,
  UndergroundPresets, UploadResponse,
} from '@/lib/types';

type Tab = 'plan' | 'das' | 'floors' | 'tunnel' | 'feeder' | 'tte';

export default function IndoorStudio({ onClose }: { onClose: () => void }) {
  const _uid = useId();
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>('plan');
  const dialogRef = useDialog(onClose);
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" style={{ width: 860 }} onClick={(e) => e.stopPropagation()}
        role="dialog" aria-modal="true" aria-labelledby="indoor-title"
        ref={dialogRef} tabIndex={-1}>
        <div className="modal-head">
          <h2 id="indoor-title">{t('indoor.title')}</h2>
          <button onClick={onClose} aria-label={t('indoor.close')}>✕</button>
        </div>
        <div className="modal-body">
          <div className="mode-tabs">
            <button className={tab === 'plan' ? 'active' : ''} aria-pressed={tab === 'plan'} onClick={() => setTab('plan')}>{t('indoor.tabPlan')}</button>
            <button className={tab === 'das' ? 'active' : ''} aria-pressed={tab === 'das'} onClick={() => setTab('das')}>{t('indoor.tabDas')}</button>
            <button className={tab === 'floors' ? 'active' : ''} aria-pressed={tab === 'floors'} onClick={() => setTab('floors')}>{t('indoor.tabFloors')}</button>
            <button className={tab === 'tunnel' ? 'active' : ''} aria-pressed={tab === 'tunnel'} onClick={() => setTab('tunnel')}>{t('indoor.tabTunnel')}</button>
            <button className={tab === 'feeder' ? 'active' : ''} aria-pressed={tab === 'feeder'} onClick={() => setTab('feeder')}>{t('indoor.tabFeeder')}</button>
            <button className={tab === 'tte' ? 'active' : ''} aria-pressed={tab === 'tte'} onClick={() => setTab('tte')}>{t('indoor.tabTte')}</button>
          </div>
          {tab === 'plan' && <PlanStudy />}
          {tab === 'das' && <DasStudy />}
          {tab === 'floors' && <FloorsStudy />}
          {tab === 'tunnel' && <TunnelStudy />}
          {tab === 'feeder' && <FeederStudy />}
          {tab === 'tte' && <TteStudy />}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- plan tab
function PlanStudy() {
  const _uid = useId();
  const { t } = useTranslation();
  const [upload, setUpload] = useState<UploadResponse | null>(null);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [layerMats, setLayerMats] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<{ url: string; bounds: [number, number, number, number] } | null>(null);
  const [tx, setTx] = useState<{ x: number; y: number } | null>(null);
  const [unitScale, setUnitScale] = useState(1.0);
  const [freqMhz, setFreqMhz] = useState(2442);
  const [txPower, setTxPower] = useState(20);
  const [sensitivity, setSensitivity] = useState(-82);
  // Multi-floor: slabs between the TX and the mapped RX floor.
  const [floors, setFloors] = useState(0);
  const [floorLoss, setFloorLoss] = useState(18.3);
  const [result, setResult] = useState<IndoorCoverageResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  // Owner-scoped now, so the browser cannot load it by URL. See lib/authedAsset.
  const heatmapSrc = useAuthedAsset(result?.png_url);

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
        floorsCrossed: floors || undefined,
        floorLossDb: floors ? floorLoss : undefined,
      }));
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <div>
      {!upload && (
        <>
          <p className="hint">{t('indoor.planIntro')}</p>
          <input type="file" accept=".dxf"
            onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])} />
          {busy && <p className="hint">{t('indoor.parsing')}</p>}
        </>
      )}

      {upload && (
        <div style={{ display: 'flex', gap: 14 }}>
          <div style={{ width: 260, flexShrink: 0 }}>
            <h3 style={{ margin: '0 0 6px', fontSize: 13 }}>{t('indoor.layerMaterials')}</h3>
            <div style={{ maxHeight: 220, overflowY: 'auto' }}>
              {upload.layers.filter((l) => l.entity_count > 0).map((l) => (
                <div key={l.name} style={{ marginBottom: 6 }}>
                  <label htmlFor={`${_uid}-0`}>{l.name} ({l.entity_count})</label>
                  <select id={`${_uid}-0`} value={layerMats[l.name] ?? 'none'}
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
                <label htmlFor={`${_uid}-1`}>{t('indoor.units')}</label>
                <select id={`${_uid}-1`} value={unitScale} onChange={(e) => setUnitScale(parseFloat(e.target.value))}>
                  <option value={1}>{t('indoor.meters')}</option>
                  <option value={0.3048}>{t('indoor.feet')}</option>
                  <option value={0.01}>{t('indoor.centimeters')}</option>
                  <option value={0.001}>{t('indoor.millimeters')}</option>
                </select>
              </div>
              <div>
                <label htmlFor={`${_uid}-2`}>{t('indoor.freqMhz')}</label>
                <input id={`${_uid}-2`} type="number" value={freqMhz}
                  onChange={(e) => setFreqMhz(parseFloat(e.target.value) || 2442)} />
              </div>
            </div>
            <div className="row">
              <div>
                <label htmlFor={`${_uid}-3`}>{t('indoor.floorsCrossed')}</label>
                <input id={`${_uid}-3`} type="number" min={0} max={30} value={floors}
                  title={t('indoor.floorsTitle')}
                  onChange={(e) => setFloors(Math.max(0, parseInt(e.target.value) || 0))} />
              </div>
              <div>
                <label htmlFor={`${_uid}-4`}>{t('indoor.floorLoss')}</label>
                <input id={`${_uid}-4`} type="number" min={0} max={40} step={0.1} value={floorLoss}
                  title={t('indoor.floorLossTitle')}
                  onChange={(e) => setFloorLoss(parseFloat(e.target.value) || 18.3)} />
              </div>
            </div>
            <div className="row">
              <div>
                <label htmlFor={`${_uid}-5`}>{t('indoor.txPower')}</label>
                <input id={`${_uid}-5`} type="number" value={txPower}
                  onChange={(e) => setTxPower(parseFloat(e.target.value) || 20)} />
              </div>
              <div>
                <label htmlFor={`${_uid}-6`}>{t('indoor.sensitivity')}</label>
                <input id={`${_uid}-6`} type="number" value={sensitivity}
                  onChange={(e) => setSensitivity(parseFloat(e.target.value) || -82)} />
              </div>
            </div>
            <button className="primary" style={{ width: '100%', marginTop: 6 }}
              disabled={!tx || busy} onClick={run}>
              {busy ? t('indoor.simulating') : tx ? t('indoor.runCoverage') : t('indoor.clickToPlace')}
            </button>
            {result && (
              <>
                <div className="stat-line" style={{ marginTop: 8 }}>
                  <span className="k">{t('indoor.servedArea')}</span>
                  <span className="v">{(result.stats.served_area_fraction * 100).toFixed(0)}%</span>
                </div>
                <div className="stat-line"><span className="k">{t('indoor.walls')}</span><span className="v">{result.stats.walls}</span></div>
                <div className="stat-line">
                  <span className="k">{t('indoor.rxDynamicRange')}</span>
                  <span className="v">{result.stats.min_rx_power_dbm.toFixed(0)} … {result.stats.max_rx_power_dbm.toFixed(0)} dBm</span>
                </div>
                <button className="download-link" type="button"
                  onClick={() => downloadAsset(result.png_url).catch(
                    (e: unknown) => setError((e as Error).message))}>
                  ⤓ {t('indoor.downloadHeatmap')}</button>
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
              <img src={heatmapSrc ?? ''} alt={t('indoor.heatmapAlt')}
                style={{ width: '100%', border: '1px solid var(--hairline)', borderRadius: 8, cursor: 'crosshair' }}
                ref={imgRef} onClick={planClick} />
            ) : preview ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={preview.url} alt={t('indoor.previewAlt')}
                style={{ width: '100%', border: '1px solid var(--hairline)', borderRadius: 8, cursor: 'crosshair' }}
                ref={imgRef} onClick={planClick} />
            ) : (
              <p className="hint">{t('indoor.noLayers')}</p>
            )}
            {tx && !result && (
              <p className="hint">{t('indoor.txAt', { x: tx.x.toFixed(1), y: tx.y.toFixed(1) })}</p>
            )}
            {preview && (
              <div className="row" style={{ maxWidth: 320 }}>
                <div>
                  <label htmlFor="tx-x">{t('indoor.txX')}</label>
                  <input id="tx-x" type="number" value={tx?.x ?? ''}
                    onChange={(e) => {
                      const v = parseFloat(e.target.value);
                      if (Number.isFinite(v)) { setTx({ x: v, y: tx?.y ?? 0 }); setResult(null); }
                    }} />
                </div>
                <div>
                  <label htmlFor="tx-y">{t('indoor.txY')}</label>
                  <input id="tx-y" type="number" value={tx?.y ?? ''}
                    onChange={(e) => {
                      const v = parseFloat(e.target.value);
                      if (Number.isFinite(v)) { setTx({ x: tx?.x ?? 0, y: v }); setResult(null); }
                    }} />
                </div>
              </div>
            )}
          </div>
        </div>
      )}
      {error && <div className="error-box" role="alert">{error}</div>}
    </div>
  );
}

// -------------------------------------------------------------- tunnel tab
function TunnelStudy() {
  const _uid = useId();
  const { t } = useTranslation();
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
      <p className="hint">{t('indoor.tunnelIntro')}</p>
      <div className="row">
        <div><label htmlFor={`${_uid}-7`}>{t('indoor.frequencyMhz')}</label><input id={`${_uid}-7`} type="number" value={freq} onChange={(e) => setFreq(parseFloat(e.target.value) || 450)} /></div>
        <div><label htmlFor={`${_uid}-8`}>{t('indoor.widthM')}</label><input id={`${_uid}-8`} type="number" value={width} onChange={(e) => setWidth(parseFloat(e.target.value) || 4)} /></div>
        <div><label htmlFor={`${_uid}-9`}>{t('indoor.heightM')}</label><input id={`${_uid}-9`} type="number" value={height} onChange={(e) => setHeight(parseFloat(e.target.value) || 3)} /></div>
        <div><label htmlFor={`${_uid}-10`}>{t('indoor.lengthM')}</label><input id={`${_uid}-10`} type="number" value={length} onChange={(e) => setLength(parseFloat(e.target.value) || 3000)} /></div>
      </div>
      <div className="row">
        <div>
          <label htmlFor={`${_uid}-11`}>{t('indoor.wallMaterial')}</label>
          <select id={`${_uid}-11`} value={wall} onChange={(e) => setWall(e.target.value)}>
            {(presets?.tunnel_walls ?? []).map((w) => (
              <option key={w.key} value={w.key}>{w.label} (εr {w.eps_r})</option>
            ))}
          </select>
        </div>
        <div><label htmlFor={`${_uid}-12`}>{t('indoor.txPower')}</label><input id={`${_uid}-12`} type="number" value={txPower} onChange={(e) => setTxPower(parseFloat(e.target.value) || 37)} /></div>
        <div><label htmlFor={`${_uid}-13`}>{t('indoor.txGain')}</label><input id={`${_uid}-13`} type="number" value={txGain} onChange={(e) => setTxGain(parseFloat(e.target.value) || 6)} /></div>
        <div><label htmlFor={`${_uid}-14`}>{t('indoor.sensitivity')}</label><input id={`${_uid}-14`} type="number" value={sensitivity} onChange={(e) => setSensitivity(parseFloat(e.target.value) || -110)} /></div>
      </div>
      <button className="primary" disabled={busy} onClick={run}>
        {busy ? t('indoor.computing') : t('indoor.computeTunnel')}
      </button>
      {result && (
        <>
          <div className="row" style={{ marginTop: 10 }}>
            <div className="stat-line"><span className="k">{t('indoor.attenuation')}</span><span className="v">{result.alpha_db_per_m.toFixed(3)} dB/m</span></div>
            <div className="stat-line"><span className="k">{t('indoor.breakpoint')}</span><span className="v">{result.breakpoint_m.toFixed(0)} m</span></div>
            <div className="stat-line"><span className="k">{t('indoor.maxRange')}</span><span className="v">{result.max_range_m.toFixed(0)} m</span></div>
          </div>
          <div style={{ height: 240 }}>
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={result.points} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
                <XAxis dataKey="d" type="number" domain={['dataMin', 'dataMax']}
                  tick={{ fontSize: 11, fill: 'var(--ink-muted)' }} stroke="var(--baseline)"
                  label={{ value: 'm', position: 'insideBottomRight', offset: -2, fontSize: 11, fill: 'var(--ink-muted)' }} />
                <YAxis width={52} tick={{ fontSize: 11, fill: 'var(--ink-muted)' }} stroke="var(--baseline)"
                  label={{ value: 'dBm', position: 'insideTopLeft', offset: 4, fontSize: 11, fill: 'var(--ink-muted)' }} />
                <Tooltip formatter={(v: number) => [`${Number(v).toFixed(1)} dBm`, t('indoor.rxPower')]}
                  labelFormatter={(l) => `${l} m`} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Area dataKey="rx_power_dbm" name={t('indoor.rxPower')} stroke="#2a78d6"
                  fill="#2a78d6" fillOpacity={0.3} strokeWidth={2} dot={false}
                  isAnimationActive={false} />
                <ReferenceLine y={sensitivity} stroke="var(--status-critical)"
                  strokeDasharray="6 4"
                  label={{ value: t('indoor.sensitivityLine'), fontSize: 11, fill: 'var(--status-critical)', position: 'insideBottomLeft' }} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
      {error && <div className="error-box" role="alert">{error}</div>}
    </div>
  );
}

// ---------------------------------------------------------- leaky-feeder tab
/**
 * Radiating-cable (leaky feeder) design — the real metro/mine tunnel solution.
 * Picking a catalog cable + frequency point autofills the physics (longitudinal
 * attenuation, coupling loss) from real vendor specs; the engine solves inline
 * amplifier spacing and reports served length / worst gap.
 */
function FeederStudy() {
  const _uid = useId();
  const { t } = useTranslation();
  const [cables, setCables] = useState<Equipment[]>([]);
  const [cableId, setCableId] = useState('');
  const [pointIdx, setPointIdx] = useState(0);
  const [freq, setFreq] = useState(450);
  const [atten, setAtten] = useState(2.0);
  const [coupling, setCoupling] = useState(65);
  const [length, setLength] = useState(2000);
  const [lateral, setLateral] = useState(2);
  const [txPower, setTxPower] = useState(20);
  const [sensitivity, setSensitivity] = useState(-95);
  const [margin, setMargin] = useState(10);
  const [ampGain, setAmpGain] = useState(30);
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchEquipment().then(({ equipment }) => {
      setCables(equipment.filter((e) => e.equipment_class === 'leaky_feeder'
        && e.leaky_feeder_specs?.points?.length));
    }).catch(() => {});
  }, []);

  const cable = cables.find((c) => c.id === cableId) ?? null;

  function applyPoint(c: Equipment | null, idx: number) {
    const pt = c?.leaky_feeder_specs?.points?.[idx];
    if (!pt) return;
    setFreq(pt.freq_mhz);
    setAtten(pt.atten_db_per_100m);
    setCoupling(pt.coupling_db_50);
  }

  async function run() {
    setBusy(true); setError(null);
    try {
      setResult(await leakyFeederStudy({
        freq_mhz: freq, length_m: length, cable_atten_db_per_100m: atten,
        coupling_ref_db: coupling,
        coupling_ref_m: cable?.leaky_feeder_specs?.coupling_ref_m ?? 2.0,
        lateral_m: lateral, tx_power_dbm: txPower,
        rx_sensitivity_dbm: sensitivity, system_margin_db: margin,
        amp_gain_db: ampGain,
      }));
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <div>
      <p className="hint">{t('indoor.feederIntro')}</p>
      <div className="row">
        <div>
          <label htmlFor={`${_uid}-15`}>{t('indoor.feederCable')}</label>
          <select id={`${_uid}-15`} value={cableId} onChange={(e) => {
            setCableId(e.target.value); setPointIdx(0);
            applyPoint(cables.find((c) => c.id === e.target.value) ?? null, 0);
          }}>
            <option value="">{t('indoor.feederManual')}</option>
            {cables.map((c) => (
              <option key={c.id} value={c.id}>{c.vendor} — {c.model}</option>
            ))}
          </select>
        </div>
        {cable && (
          <div>
            <label htmlFor={`${_uid}-16`}>{t('indoor.feederBand')}</label>
            <select id={`${_uid}-16`} value={pointIdx} onChange={(e) => {
              const i = parseInt(e.target.value, 10);
              setPointIdx(i); applyPoint(cable, i);
            }}>
              {cable.leaky_feeder_specs!.points.map((p, i) => (
                <option key={i} value={i}>
                  {p.freq_mhz} MHz — {p.atten_db_per_100m} dB/100m
                </option>
              ))}
            </select>
          </div>
        )}
      </div>
      {cable?.spec_confidence && cable.spec_confidence !== 'datasheet' && (
        <p className="hint">⚠ {t('indoor.feederConfidence')}</p>
      )}
      <div className="row">
        <div><label htmlFor={`${_uid}-17`}>{t('indoor.frequencyMhz')}</label><input id={`${_uid}-17`} type="number" value={freq} onChange={(e) => setFreq(parseFloat(e.target.value) || 450)} /></div>
        <div><label htmlFor={`${_uid}-18`}>{t('indoor.feederAtten')}</label><input id={`${_uid}-18`} type="number" step="0.01" value={atten} onChange={(e) => setAtten(parseFloat(e.target.value) || 2)} /></div>
        <div><label htmlFor={`${_uid}-19`}>{t('indoor.feederCoupling')}</label><input id={`${_uid}-19`} type="number" value={coupling} onChange={(e) => setCoupling(parseFloat(e.target.value) || 65)} /></div>
        <div><label htmlFor={`${_uid}-20`}>{t('indoor.lengthM')}</label><input id={`${_uid}-20`} type="number" value={length} onChange={(e) => setLength(parseFloat(e.target.value) || 2000)} /></div>
      </div>
      <div className="row">
        <div><label htmlFor={`${_uid}-21`}>{t('indoor.feederLateral')}</label><input id={`${_uid}-21`} type="number" value={lateral} onChange={(e) => setLateral(parseFloat(e.target.value) || 2)} /></div>
        <div><label htmlFor={`${_uid}-22`}>{t('indoor.txPower')}</label><input id={`${_uid}-22`} type="number" value={txPower} onChange={(e) => setTxPower(parseFloat(e.target.value) || 20)} /></div>
        <div><label htmlFor={`${_uid}-23`}>{t('indoor.sensitivity')}</label><input id={`${_uid}-23`} type="number" value={sensitivity} onChange={(e) => setSensitivity(parseFloat(e.target.value) || -95)} /></div>
        <div><label htmlFor={`${_uid}-24`}>{t('indoor.feederMargin')}</label><input id={`${_uid}-24`} type="number" value={margin} onChange={(e) => setMargin(parseFloat(e.target.value) || 0)} /></div>
        <div><label htmlFor={`${_uid}-25`}>{t('indoor.feederAmpGain')}</label><input id={`${_uid}-25`} type="number" value={ampGain} onChange={(e) => setAmpGain(parseFloat(e.target.value) || 0)} /></div>
      </div>
      <button className="primary" disabled={busy} onClick={run}>
        {busy ? t('indoor.computing') : t('indoor.computeFeeder')}
      </button>
      {result && (
        <>
          <div className="row" style={{ marginTop: 10 }}>
            {result.amp_spacing_m != null && (
              <div className="stat-line"><span className="k">{t('indoor.feederAmpSpacing')}</span><span className="v">{result.amp_spacing_m.toFixed(0)} m × {result.amps_required}</span></div>
            )}
            <div className="stat-line"><span className="k">{t('indoor.feederServed')}</span><span className="v">{(result.served_length_fraction * 100).toFixed(1)} %</span></div>
            <div className="stat-line"><span className="k">{t('indoor.feederWorstGap')}</span><span className="v">{result.worst_gap_m.toFixed(0)} m</span></div>
          </div>
          <div style={{ height: 240 }}>
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={result.points} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
                <XAxis dataKey="x_m" type="number" domain={['dataMin', 'dataMax']}
                  tick={{ fontSize: 11, fill: 'var(--ink-muted)' }} stroke="var(--baseline)"
                  label={{ value: 'm', position: 'insideBottomRight', offset: -2, fontSize: 11, fill: 'var(--ink-muted)' }} />
                <YAxis width={52} tick={{ fontSize: 11, fill: 'var(--ink-muted)' }} stroke="var(--baseline)"
                  label={{ value: 'dBm', position: 'insideTopLeft', offset: 4, fontSize: 11, fill: 'var(--ink-muted)' }} />
                <Tooltip formatter={(v: number) => [`${Number(v).toFixed(1)} dBm`, t('indoor.feederField')]}
                  labelFormatter={(l) => `${l} m`} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Area dataKey="field_dbm" name={t('indoor.feederField')} stroke="#12b3a6"
                  fill="#12b3a6" fillOpacity={0.3} strokeWidth={2} dot={false}
                  isAnimationActive={false} />
                <ReferenceLine y={result.required_field_dbm} stroke="var(--status-critical)"
                  strokeDasharray="6 4"
                  label={{ value: t('indoor.feederRequired'), fontSize: 11, fill: 'var(--status-critical)', position: 'insideBottomLeft' }} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
      {error && <div className="error-box" role="alert">{error}</div>}
    </div>
  );
}

// ----------------------------------------------------------------- TTE tab
function TteStudy() {
  const _uid = useId();
  const { t } = useTranslation();
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
      <p className="hint">{t('indoor.tteIntro')}</p>
      <div className="row">
        <div><label htmlFor={`${_uid}-26`}>{t('indoor.frequencyHz')}</label><input id={`${_uid}-26`} type="number" value={freqHz} onChange={(e) => setFreqHz(parseFloat(e.target.value) || 5000)} /></div>
        <div><label htmlFor={`${_uid}-27`}>{t('indoor.depthM')}</label><input id={`${_uid}-27`} type="number" value={depth} onChange={(e) => setDepth(parseFloat(e.target.value) || 100)} /></div>
        <div>
          <label htmlFor={`${_uid}-28`}>{t('indoor.ground')}</label>
          <select id={`${_uid}-28`} value={earth} onChange={(e) => setEarth(e.target.value)}>
            {(presets?.earth ?? []).map((g) => (
              <option key={g.key} value={g.key}>{g.label} ({g.sigma} S/m)</option>
            ))}
          </select>
        </div>
      </div>
      <div className="row">
        <div><label htmlFor={`${_uid}-29`}>{t('indoor.txPower')}</label><input id={`${_uid}-29`} type="number" value={txPower} onChange={(e) => setTxPower(parseFloat(e.target.value) || 30)} /></div>
        <div><label htmlFor={`${_uid}-30`}>{t('indoor.sensitivity')}</label><input id={`${_uid}-30`} type="number" value={sensitivity} onChange={(e) => setSensitivity(parseFloat(e.target.value) || -130)} /></div>
      </div>
      <button className="primary" disabled={busy} onClick={run}>
        {busy ? t('indoor.computing') : t('indoor.computeTte')}
      </button>
      {result && (
        <div style={{ marginTop: 10 }}>
          <div className="stat-line"><span className="k">{t('indoor.skinDepth')}</span><span className="v">{result.skin_depth_m.toFixed(1)} m</span></div>
          <div className="stat-line"><span className="k">{t('indoor.groundAtten')}</span><span className="v">{result.attenuation_db.toFixed(1)} dB</span></div>
          <div className="stat-line"><span className="k">{t('indoor.nearFieldSpread')}</span><span className="v">{result.spreading_db.toFixed(1)} dB</span></div>
          <div className="stat-line"><span className="k">{t('indoor.totalLoss')}</span><span className="v">{result.total_loss_db.toFixed(1)} dB</span></div>
          <div className="stat-line"><span className="k">{t('indoor.rxPower')}</span><span className="v">{result.rx_power_dbm.toFixed(1)} dBm</span></div>
          <div className="stat-line">
            <span className="k">{t('indoor.margin')}</span>
            <span className="v" style={{ color: result.served ? 'var(--status-good)' : 'var(--status-critical)' }}>
              {result.margin_db.toFixed(1)} dB {result.served ? t('indoor.linkWorks') : t('indoor.noLink')}
            </span>
          </div>
        </div>
      )}
      {error && <div className="error-box" role="alert">{error}</div>}
    </div>
  );
}
// ------------------------------------------------------------------ DAS tab
type DasAntenna = { x: number; y: number; gain: number; cableLen: number; tapDb: number };

function DasStudy() {
  const _uid = useId();
  const { t } = useTranslation();
  const [upload, setUpload] = useState<UploadResponse | null>(null);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [layerMats, setLayerMats] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<{ url: string; bounds: [number, number, number, number] } | null>(null);
  const [unitScale, setUnitScale] = useState(1.0);
  const [freqMhz, setFreqMhz] = useState(2442);
  const [srcPower, setSrcPower] = useState(30);
  const [topology, setTopology] = useState<'star' | 'cascade'>('star');
  const [trunkLen, setTrunkLen] = useState(20);
  const [cableLoss, setCableLoss] = useState(10);   // dB/100m (LMR-400 class @2.4 GHz)
  const [antennas, setAntennas] = useState<DasAntenna[]>([]);
  const [result, setResult] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  // Owner-scoped now, so the browser cannot load it by URL. See lib/authedAsset.
  const heatmapSrc = useAuthedAsset(result?.png_url);

  useEffect(() => { fetchMaterials().then(setMaterials).catch(() => {}); }, []);

  function guessMat(name: string): string {
    const n = name.toLowerCase();
    if (/(concrete|beton)/.test(n)) return 'concrete';
    if (/(glass|window|fenetre)/.test(n)) return 'glass';
    if (/(metal|steel)/.test(n)) return 'metal';
    if (/(door|porte|wood)/.test(n)) return 'wood';
    if (/(wall|mur|masonry|brick)/.test(n)) return 'brick';
    return 'drywall';
  }

  async function handleFile(file: File) {
    setBusy(true); setError(null); setResult(null); setPreview(null); setAntennas([]);
    try {
      const up = await uploadDxf(file);
      setUpload(up);
      const defaults: Record<string, string> = {};
      for (const l of up.layers) defaults[l.name] = l.entity_count > 0 ? guessMat(l.name) : 'none';
      setLayerMats(defaults);
      await refreshPreview(up.dxf_id, defaults);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  async function refreshPreview(dxfId: string, mats: Record<string, string>) {
    const active = Object.entries(mats).filter(([, m]) => m !== 'none').map(([l]) => l);
    if (!active.length) { setPreview(null); return; }
    try { setPreview(await fetchPlanPreview(dxfId, active)); }
    catch (e) { setError((e as Error).message); }
  }

  function planClick(e: React.MouseEvent<HTMLImageElement>) {
    if (!preview || !imgRef.current || antennas.length >= 32) return;
    const rect = imgRef.current.getBoundingClientRect();
    const [x0, y0, x1, y1] = preview.bounds;
    const fx = (e.clientX - rect.left) / rect.width;
    const fy = (e.clientY - rect.top) / rect.height;
    setAntennas((prev) => [...prev, {
      x: x0 + fx * (x1 - x0), y: y1 - fy * (y1 - y0),
      gain: 2, cableLen: 10, tapDb: 10,
    }]);
    setResult(null);
  }

  // Build the backend component tree from the flat antenna list.
  function buildTree(): object {
    const antNode = (a: DasAntenna) =>
      ({ component: 'antenna', x: a.x, y: a.y, gain_dbi: a.gain });
    const cable = (len: number, child: object) =>
      ({ component: 'cable', length_m: len, loss_db_per_100m: cableLoss, children: [child] });
    if (topology === 'star') {
      if (antennas.length === 1) return cable(trunkLen + antennas[0].cableLen, antNode(antennas[0]));
      return cable(trunkLen, {
        component: 'splitter', ways: antennas.length, excess_db: 0.5,
        children: antennas.map((a) => cable(a.cableLen, antNode(a))),
      });
    }
    // Cascade: source → trunk → [coupler(tap → antenna) → cable]* → last antenna.
    let chain: object = antNode(antennas[antennas.length - 1]);
    for (let i = antennas.length - 2; i >= 0; i--) {
      chain = {
        component: 'coupler', coupling_db: antennas[i].tapDb, insertion_db: 0.5,
        children: [cable(antennas[i + 1].cableLen, chain), antNode(antennas[i])],
      };
    }
    return cable(trunkLen, chain);
  }

  async function run() {
    if (!upload || antennas.length === 0) return;
    setBusy(true); setError(null);
    try {
      setResult(await dasSolve({
        dxf_id: upload.dxf_id, layer_materials: layerMats, unit_scale: unitScale,
        freq_mhz: freqMhz, source_power_dbm: srcPower, tree: buildTree(),
      }));
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <div>
      {!upload && (
        <>
          <p className="hint">{t('indoor.dasIntro')}</p>
          <input type="file" accept=".dxf"
            onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])} />
          {busy && <p className="hint">{t('indoor.parsing')}</p>}
        </>
      )}
      {upload && (
        <div style={{ display: 'flex', gap: 14 }}>
          <div style={{ width: 280, flexShrink: 0 }}>
            <div className="row">
              <div>
                <label htmlFor={`${_uid}-31`}>{t('indoor.dasTopology')}</label>
                <select id={`${_uid}-31`} value={topology} onChange={(e) => { setTopology(e.target.value as 'star' | 'cascade'); setResult(null); }}>
                  <option value="star">{t('indoor.dasStar')}</option>
                  <option value="cascade">{t('indoor.dasCascade')}</option>
                </select>
              </div>
              <div>
                <label htmlFor={`${_uid}-32`}>{t('indoor.freqMhz')}</label>
                <input id={`${_uid}-32`} type="number" value={freqMhz} onChange={(e) => setFreqMhz(parseFloat(e.target.value) || 2442)} />
              </div>
            </div>
            <div className="row">
              <div>
                <label htmlFor={`${_uid}-33`}>{t('indoor.dasSource')}</label>
                <input id={`${_uid}-33`} type="number" value={srcPower} onChange={(e) => setSrcPower(parseFloat(e.target.value) || 30)} />
              </div>
              <div>
                <label htmlFor={`${_uid}-34`}>{t('indoor.dasTrunk')}</label>
                <input id={`${_uid}-34`} type="number" min={0} value={trunkLen} onChange={(e) => setTrunkLen(Math.max(0, parseFloat(e.target.value) || 0))} />
              </div>
            </div>
            <div className="row">
              <div>
                <label htmlFor={`${_uid}-35`}>{t('indoor.dasCableLoss')}</label>
                <input id={`${_uid}-35`} type="number" min={0} step={0.1} value={cableLoss}
                  title="Coax attenuation in dB per 100 m at the design frequency (LMR-400 ≈ 10 dB/100 m at 2.4 GHz, 1/2″ superflex ≈ 7)"
                  onChange={(e) => setCableLoss(Math.max(0, parseFloat(e.target.value) || 0))} />
              </div>
              <div>
                <label htmlFor={`${_uid}-36`}>{t('indoor.units')}</label>
                <select id={`${_uid}-36`} value={unitScale} onChange={(e) => setUnitScale(parseFloat(e.target.value))}>
                  <option value={1}>{t('indoor.meters')}</option>
                  <option value={0.3048}>{t('indoor.feet')}</option>
                  <option value={0.01}>{t('indoor.centimeters')}</option>
                  <option value={0.001}>{t('indoor.millimeters')}</option>
                </select>
              </div>
            </div>
            <h3 style={{ margin: '8px 0 4px', fontSize: 13 }}>
              {t('indoor.dasAntennas', { count: antennas.length })}
            </h3>
            {/* Placement used to exist only as a click on the plan <img>, so a
                keyboard or screen-reader user could never add an antenna and
                the Run button below stayed disabled forever.  This adds one at
                the centre of the plan; the X/Y fields on each row then position
                it exactly, no pointer involved. */}
            <button style={{ width: '100%', marginBottom: 4 }}
              disabled={!preview || antennas.length >= 32}
              onClick={() => {
                if (!preview || antennas.length >= 32) return;
                const [x0, y0, x1, y1] = preview.bounds;
                setAntennas((prev) => [...prev, {
                  x: (x0 + x1) / 2, y: (y0 + y1) / 2,
                  gain: 2, cableLen: 10, tapDb: 10,
                }]);
                setResult(null);
              }}>
              + {t('indoor.dasAddAntenna')}
            </button>
            <div style={{ maxHeight: 190, overflowY: 'auto' }}>
              {antennas.map((a, i) => (
                <div key={i} style={{ borderBottom: '1px solid var(--hairline)', padding: '3px 0', fontSize: 11 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <b>#{i + 1}</b>
                    <span>({a.x.toFixed(1)}, {a.y.toFixed(1)})</span>
                    <button style={{ padding: '0 6px' }} aria-label={`Remove antenna ${i + 1}`}
                      onClick={() => { setAntennas((p) => p.filter((_, j) => j !== i)); setResult(null); }}>−</button>
                  </div>
                  <div className="row">
                    <div>
                      <label htmlFor={`${_uid}-ax-${i}`}>X</label>
                      <input id={`${_uid}-ax-${i}`} type="number" step={0.5} value={a.x}
                        onChange={(e) => { const v = parseFloat(e.target.value) || 0; setAntennas((p) => p.map((x, j) => j === i ? { ...x, x: v } : x)); setResult(null); }} />
                    </div>
                    <div>
                      <label htmlFor={`${_uid}-ay-${i}`}>Y</label>
                      <input id={`${_uid}-ay-${i}`} type="number" step={0.5} value={a.y}
                        onChange={(e) => { const v = parseFloat(e.target.value) || 0; setAntennas((p) => p.map((x, j) => j === i ? { ...x, y: v } : x)); setResult(null); }} />
                    </div>
                  </div>
                  <div className="row">
                    <div>
                      <label htmlFor={`${_uid}-37-${i}`}>{t('indoor.dasGain')}</label>
                      <input id={`${_uid}-37-${i}`} type="number" step={0.5} value={a.gain}
                        onChange={(e) => { const v = parseFloat(e.target.value) || 0; setAntennas((p) => p.map((x, j) => j === i ? { ...x, gain: v } : x)); setResult(null); }} />
                    </div>
                    <div>
                      <label htmlFor={`${_uid}-38-${i}`}>{t('indoor.dasCable')}</label>
                      <input id={`${_uid}-38-${i}`} type="number" min={0} value={a.cableLen}
                        onChange={(e) => { const v = Math.max(0, parseFloat(e.target.value) || 0); setAntennas((p) => p.map((x, j) => j === i ? { ...x, cableLen: v } : x)); setResult(null); }} />
                    </div>
                    {topology === 'cascade' && i < antennas.length - 1 && (
                      <div>
                        <label htmlFor={`${_uid}-39-${i}`}>{t('indoor.dasTap')}</label>
                        <input id={`${_uid}-39-${i}`} type="number" min={1} value={a.tapDb}
                          onChange={(e) => { const v = Math.max(1, parseFloat(e.target.value) || 1); setAntennas((p) => p.map((x, j) => j === i ? { ...x, tapDb: v } : x)); setResult(null); }} />
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
            <button className="primary" style={{ width: '100%', marginTop: 6 }}
              disabled={antennas.length === 0 || busy} onClick={run}>
              {busy ? t('indoor.simulating')
                : antennas.length ? t('indoor.dasSolve') : t('indoor.dasClickToPlace')}
            </button>
            {result && (
              <>
                <div className="stat-line" style={{ marginTop: 8 }}>
                  <span className="k">{t('indoor.servedArea')}</span>
                  <span className="v">{(result.stats.served_area_fraction * 100).toFixed(0)}%</span>
                </div>
                {result.antennas.map((a: any, i: number) => {
                  // The solver walks the tree, so its order can differ from
                  // placement order — label rows by the matching UI antenna.
                  const idx = antennas.findIndex(
                    (u) => Math.abs(u.x - a.x) < 1e-6 && Math.abs(u.y - a.y) < 1e-6);
                  return (
                    <div key={i} className="stat-line" title={a.path}>
                      <span className="k">#{idx >= 0 ? idx + 1 : '?'}</span>
                      <span className="v">{a.input_power_dbm} dBm → EIRP {a.eirp_dbm} dBm</span>
                    </div>
                  );
                })}
              </>
            )}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            {result ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={heatmapSrc ?? ''} alt={t('indoor.heatmapAlt')} ref={imgRef} onClick={planClick}
                style={{ width: '100%', border: '1px solid var(--hairline)', borderRadius: 8, cursor: 'crosshair' }} />
            ) : preview ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={preview.url} alt={t('indoor.previewAlt')} ref={imgRef} onClick={planClick}
                style={{ width: '100%', border: '1px solid var(--hairline)', borderRadius: 8, cursor: 'crosshair' }} />
            ) : (
              <p className="hint">{t('indoor.noLayers')}</p>
            )}
            <p className="hint">{t('indoor.dasPlaceHint')}</p>
          </div>
        </div>
      )}
      {error && <div className="error-box" role="alert">{error}</div>}
    </div>
  );
}

// --------------------------------------------------------------- floors tab
type FloorEntry = { level: number; dxfId: string; name: string;
                    layerMats: Record<string, string> };

function FloorsStudy() {
  const _uid = useId();
  const { t } = useTranslation();
  const [materials, setMaterials] = useState<Material[]>([]);
  const [floors, setFloors] = useState<FloorEntry[]>([]);
  const [viewLevel, setViewLevel] = useState(0);
  const [preview, setPreview] = useState<{ url: string; bounds: [number, number, number, number] } | null>(null);
  const [tx, setTx] = useState<{ x: number; y: number } | null>(null);
  const [txLevel, setTxLevel] = useState(0);
  const [unitScale, setUnitScale] = useState(1.0);
  const [freqMhz, setFreqMhz] = useState(2442);
  const [txPower, setTxPower] = useState(20);
  const [floorLoss, setFloorLoss] = useState(18.3);
  const [result, setResult] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);

  useEffect(() => { fetchMaterials().then(setMaterials).catch(() => {}); }, []);

  function guessMat(name: string): string {
    const n = name.toLowerCase();
    if (/(concrete|beton)/.test(n)) return 'concrete';
    if (/(glass|window|fenetre)/.test(n)) return 'glass';
    if (/(metal|steel)/.test(n)) return 'metal';
    if (/(door|porte|wood)/.test(n)) return 'wood';
    if (/(wall|mur|masonry|brick)/.test(n)) return 'brick';
    return 'drywall';
  }

  const nextLevel = () =>
    floors.length ? Math.max(...floors.map((f) => f.level)) + 1 : 0;

  async function addFloorFile(file: File) {
    setBusy(true); setError(null); setResult(null);
    try {
      const up = await uploadDxf(file);
      const mats: Record<string, string> = {};
      for (const l of up.layers) mats[l.name] = l.entity_count > 0 ? guessMat(l.name) : 'none';
      const lvl = nextLevel();
      setFloors((prev) => [...prev, { level: lvl, dxfId: up.dxf_id, name: file.name, layerMats: mats }]);
      setViewLevel(lvl);
      await showPreview(up.dxf_id, mats);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  function duplicateTopFloor() {
    const top = floors[floors.length - 1];
    if (!top) return;
    setFloors((prev) => [...prev, { ...top, level: nextLevel() }]);
    setResult(null);
  }

  async function showPreview(dxfId: string, mats: Record<string, string>) {
    const active = Object.entries(mats).filter(([, m]) => m !== 'none').map(([l]) => l);
    if (!active.length) { setPreview(null); return; }
    try { setPreview(await fetchPlanPreview(dxfId, active)); }
    catch (e) { setError((e as Error).message); }
  }

  function selectLevel(lvl: number) {
    setViewLevel(lvl);
    const f = floors.find((x) => x.level === lvl);
    if (f) showPreview(f.dxfId, f.layerMats);
  }

  function planClick(e: React.MouseEvent<HTMLImageElement>) {
    if (!preview || !imgRef.current) return;
    const rect = imgRef.current.getBoundingClientRect();
    const [x0, y0, x1, y1] = preview.bounds;
    const fx = (e.clientX - rect.left) / rect.width;
    const fy = (e.clientY - rect.top) / rect.height;
    setTx({ x: x0 + fx * (x1 - x0), y: y1 - fy * (y1 - y0) });
    setTxLevel(viewLevel);
    setResult(null);
  }

  async function run() {
    if (!floors.length || !tx) return;
    setBusy(true); setError(null);
    try {
      const resp = await indoorStack({
        floors: floors.map((f) => ({ level: f.level, dxf_id: f.dxfId, layer_materials: f.layerMats })),
        tx_level: txLevel, tx_x: tx.x, tx_y: tx.y,
        unit_scale: unitScale, freq_mhz: freqMhz, tx_power_dbm: txPower,
        floor_loss_db: floorLoss,
      });
      setResult(resp);
      setViewLevel(txLevel);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  const resultFloor = result?.floors?.find((f: any) => f.level === viewLevel);
  // Owner-scoped now, so the browser cannot load it by URL. See lib/authedAsset.
  const heatmapSrc = useAuthedAsset(resultFloor?.png_url);

  return (
    <div>
      <p className="hint">{t('indoor.floorsIntro')}</p>
      <div className="row" style={{ alignItems: 'flex-end' }}>
        <div>
          <label htmlFor={`${_uid}-40`}>{t('indoor.floorsAdd')}</label>
          <input id={`${_uid}-40`} type="file" accept=".dxf"
            onChange={(e) => { if (e.target.files?.[0]) { addFloorFile(e.target.files[0]); e.target.value = ''; } }} />
        </div>
        {floors.length > 0 && (
          <button onClick={duplicateTopFloor}>{t('indoor.floorsDuplicate')}</button>
        )}
      </div>
      {floors.length > 0 && (
        <div style={{ display: 'flex', gap: 14, marginTop: 8 }}>
          <div style={{ width: 270, flexShrink: 0 }}>
            <div style={{ maxHeight: 130, overflowY: 'auto' }}>
              {floors.map((f) => (
                <div key={f.level} className="stat-line">
                  <span className="k">
                    {t('indoor.floorsLevel')} {f.level}{f.level === txLevel && tx ? ' 📡' : ''}
                  </span>
                  <span className="v">
                    {f.name.slice(0, 16)}
                    <button style={{ marginLeft: 6, padding: '0 6px' }} aria-label={`Remove level ${f.level}`}
                      onClick={() => { setFloors((p) => p.filter((x) => x.level !== f.level)); setResult(null); }}>−</button>
                  </span>
                </div>
              ))}
            </div>
            <div className="row" style={{ marginTop: 6 }}>
              <div>
                <label htmlFor={`${_uid}-41`}>{t('indoor.freqMhz')}</label>
                <input id={`${_uid}-41`} type="number" value={freqMhz} onChange={(e) => setFreqMhz(parseFloat(e.target.value) || 2442)} />
              </div>
              <div>
                <label htmlFor={`${_uid}-42`}>{t('indoor.txPower')}</label>
                <input id={`${_uid}-42`} type="number" value={txPower} onChange={(e) => setTxPower(parseFloat(e.target.value) || 20)} />
              </div>
            </div>
            <div className="row">
              <div>
                <label htmlFor={`${_uid}-43`}>{t('indoor.floorLoss')}</label>
                <input id={`${_uid}-43`} type="number" min={0} max={40} step={0.1} value={floorLoss}
                  onChange={(e) => setFloorLoss(parseFloat(e.target.value) || 18.3)} />
              </div>
              <div>
                <label htmlFor={`${_uid}-44`}>{t('indoor.units')}</label>
                <select id={`${_uid}-44`} value={unitScale} onChange={(e) => setUnitScale(parseFloat(e.target.value))}>
                  <option value={1}>{t('indoor.meters')}</option>
                  <option value={0.3048}>{t('indoor.feet')}</option>
                  <option value={0.01}>{t('indoor.centimeters')}</option>
                  <option value={0.001}>{t('indoor.millimeters')}</option>
                </select>
              </div>
            </div>
            <button className="primary" style={{ width: '100%', marginTop: 6 }}
              disabled={!tx || busy} onClick={run}>
              {busy ? t('indoor.simulating') : tx
                ? t('indoor.floorsRun', { count: floors.length })
                : t('indoor.clickToPlace')}
            </button>
            {result && (
              <>
                <div className="stat-line" style={{ marginTop: 8 }}>
                  <span className="k">{t('indoor.floorsBuildingMean')}</span>
                  <span className="v">{(result.building_mean_served_fraction * 100).toFixed(0)}%</span>
                </div>
                {result.floors.map((f: any) => (
                  <div key={f.level} className="stat-line">
                    <span className="k">{t('indoor.floorsLevel')} {f.level}
                      {f.level === result.tx_level ? ' 📡' : ` (+${f.floors_crossed})`}</span>
                    <span className="v">{(f.stats.served_area_fraction * 100).toFixed(0)}%</span>
                  </div>
                ))}
              </>
            )}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="row" style={{ flexWrap: 'wrap', gap: 4, marginBottom: 6 }}>
              {floors.map((f) => (
                <button key={f.level} className={viewLevel === f.level ? 'primary' : ''}
                  onClick={() => selectLevel(f.level)}>
                  {t('indoor.floorsLevel')} {f.level}
                </button>
              ))}
            </div>
            {resultFloor ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={heatmapSrc ?? ''} alt={t('indoor.heatmapAlt')} ref={imgRef} onClick={planClick}
                style={{ width: '100%', border: '1px solid var(--hairline)', borderRadius: 8, cursor: 'crosshair' }} />
            ) : preview ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={preview.url} alt={t('indoor.previewAlt')} ref={imgRef} onClick={planClick}
                style={{ width: '100%', border: '1px solid var(--hairline)', borderRadius: 8, cursor: 'crosshair' }} />
            ) : (
              <p className="hint">{t('indoor.noLayers')}</p>
            )}
            {tx && (
              <p className="hint">
                {t('indoor.floorsTxAt', { level: txLevel, x: tx.x.toFixed(1), y: tx.y.toFixed(1) })}
              </p>
            )}
          </div>
        </div>
      )}
      {error && <div className="error-box" role="alert">{error}</div>}
    </div>
  );
}
