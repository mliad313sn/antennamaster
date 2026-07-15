'use client';

/**
 * Radio study panel: pick a technology preset (2G GSM ... 5G NR mmWave,
 * PMR, broadcast, Wi-Fi, IoT, microwave PtP), optionally override the
 * propagation model / environment, and run an area coverage simulation from
 * the TX site.  Shows the coverage legend and the point-to-point link budget
 * of the current profile.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  fetchAntennas, fetchModels, fetchTechnologies, simulateCoverage,
  simulateMultiCoverage, uploadAntenna,
} from '@/lib/api';
import Help from '@/components/Help';
import type {
  AntennaInfo, CoverageResponse, LatLng, ModelInfo, SiteEntry, StudyResult,
  Technology,
} from '@/lib/types';

export interface StudyPanelProps {
  tx: LatLng | null;
  dxfId: string | null;
  txHeight: number;
  technology: string | null;
  onTechnologyChange: (key: string | null) => void;
  model: string | null;
  onModelChange: (key: string | null) => void;
  environment: string | null;
  onEnvironmentChange: (env: string | null) => void;
  // Environmental excess losses (shared with the profile study in page.tsx).
  foliageDepth: number;
  onFoliageChange: (v: number) => void;
  rainRate: number;
  onRainChange: (v: number) => void;
  clutterPct: number;
  onClutterChange: (v: number) => void;
  surfaceOn: boolean;
  onSurfaceChange: (v: boolean) => void;
  surfaceAvailable: boolean;
  study: StudyResult | null;
  coverage: CoverageResponse | null;
  onCoverage: (c: CoverageResponse | null) => void;
}

export default function StudyPanel(props: StudyPanelProps) {
  const { t } = useTranslation();
  const [techs, setTechs] = useState<Technology[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [radiusKm, setRadiusKm] = useState(8);
  const [sector, setSector] = useState(false);
  const [azimuth, setAzimuth] = useState(0);
  const [beamwidth, setBeamwidth] = useState(65);
  const [downtilt, setDowntilt] = useState(0);
  const [shadowMargin, setShadowMargin] = useState(0);
  // Real-site link budget overrides (empty = use the preset value).
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [ovrPower, setOvrPower] = useState('');
  const [ovrTxGain, setOvrTxGain] = useState('');
  const [ovrRxGain, setOvrRxGain] = useState('');
  const [ovrLosses, setOvrLosses] = useState('');
  const [ovrSens, setOvrSens] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Measured antenna patterns (MSI Planet uploads).
  const [antennas, setAntennas] = useState<AntennaInfo[]>([]);
  const [antennaId, setAntennaId] = useState<string | null>(null);
  // Multi-site best-server study; the raw response is kept so the map
  // overlay can be flipped between best-server and SINR views.
  const [sites, setSites] = useState<SiteEntry[]>([]);
  const [multiRaw, setMultiRaw] = useState<CoverageResponse | null>(null);
  const [sinrView, setSinrView] = useState(false);

  function showMultiView(sinr: boolean) {
    if (!multiRaw) return;
    setSinrView(sinr);
    props.onCoverage(sinr && multiRaw.sinr
      ? { ...multiRaw, png_url: multiRaw.sinr.png_url,
          legend: multiRaw.sinr.legend }
      : multiRaw);
  }

  const numOr = (s: string) => {
    const v = parseFloat(s);
    return Number.isFinite(v) ? v : undefined;
  };

  useEffect(() => {
    fetchTechnologies().then(setTechs).catch(() => setTechs([]));
    fetchModels().then(setModels).catch(() => setModels([]));
    fetchAntennas().then(setAntennas).catch(() => setAntennas([]));
  }, []);

  async function handleAntennaFile(file: File) {
    setError(null);
    try {
      const info = await uploadAntenna(file);
      setAntennas((prev) => [...prev, info]);
      setAntennaId(info.antenna_id);
    } catch (e) { setError((e as Error).message); }
  }

  async function runMultiCoverage() {
    if (!props.technology || sites.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const resp = await simulateMultiCoverage({
        sites, technology: props.technology, radiusKm,
        dxfId: props.dxfId, antennaId,
        model: props.model, environment: props.environment,
        shadowMarginDb: shadowMargin, hBsM: props.txHeight || undefined,
        clutterPct: props.clutterPct || undefined,
        surface: props.surfaceOn || undefined,
        txPowerDbm: numOr(ovrPower), rxSensitivityDbm: numOr(ovrSens),
      });
      setMultiRaw(resp);
      setSinrView(false);
      props.onCoverage(resp);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  const selectedTech = useMemo(
    () => techs.find((t) => t.key === props.technology) ?? null,
    [techs, props.technology]);
  const activeModel = useMemo(
    () => models.find((m) => m.key === (props.model ?? selectedTech?.model)) ?? null,
    [models, props.model, selectedTech]);

  // Group presets by generation for a readable dropdown.
  const groups = useMemo(() => {
    const g = new Map<string, Technology[]>();
    for (const t of techs) {
      if (!g.has(t.generation)) g.set(t.generation, []);
      g.get(t.generation)!.push(t);
    }
    return Array.from(g.entries());
  }, [techs]);

  async function runCoverage() {
    if (!props.tx || !props.technology) return;
    setBusy(true);
    setError(null);
    try {
      const resp = await simulateCoverage({
        lat: props.tx.lat, lon: props.tx.lng,
        technology: props.technology, radiusKm,
        dxfId: props.dxfId,
        model: props.model, environment: props.environment,
        antennaAzimuthDeg: (sector || antennaId) ? azimuth : null,
        antennaBeamwidthDeg: beamwidth,
        downtiltDeg: downtilt,
        antennaId,
        shadowMarginDb: shadowMargin,
        foliageDepthM: props.foliageDepth || undefined,
        rainRateMmH: props.rainRate || undefined,
        clutterPct: props.clutterPct || undefined,
        surface: props.surfaceOn || undefined,
        hBsM: props.txHeight || undefined,
        txPowerDbm: numOr(ovrPower), txGainDbi: numOr(ovrTxGain),
        rxGainDbi: numOr(ovrRxGain), lossesDb: numOr(ovrLosses),
        rxSensitivityDbm: numOr(ovrSens),
      });
      setMultiRaw(null);
      setSinrView(false);
      props.onCoverage(resp);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <h3 data-tour="technology">{t('study.title')}</h3>
      <label>{t('study.technology')}</label>
      <select
        value={props.technology ?? ''}
        onChange={(e) => {
          props.onTechnologyChange(e.target.value || null);
          props.onModelChange(null);
          props.onEnvironmentChange(null);
        }}
      >
        <option value="">{t('study.none')}</option>
        {groups.map(([gen, list]) => (
          <optgroup key={gen} label={gen}>
            {list.map((t) => (
              <option key={t.key} value={t.key}>{t.label}</option>
            ))}
          </optgroup>
        ))}
      </select>

      {selectedTech && (
        <>
          <div className="row" style={{ marginTop: 8 }}>
            <div>
              <label>{t('study.model')}</label>
              <select
                value={props.model ?? selectedTech.model}
                onChange={(e) => props.onModelChange(e.target.value)}
              >
                {models.map((m) => (
                  <option key={m.key} value={m.key}>{m.label}</option>
                ))}
              </select>
            </div>
          </div>
          {activeModel && activeModel.environments.length > 0 && (
            <div>
              <label>{t('study.environment')}</label>
              <select
                value={props.environment ?? selectedTech.environment}
                onChange={(e) => props.onEnvironmentChange(e.target.value)}
              >
                {activeModel.environments.map((env) => (
                  <option key={env} value={env}>{env}</option>
                ))}
              </select>
            </div>
          )}
          <div className="stat-line" style={{ marginTop: 6 }}>
            <span className="k">{t('study.preset')}</span>
            <span className="v">
              {selectedTech.freq_mhz.toLocaleString()} MHz ·
              TX {selectedTech.tx_power_dbm} dBm · sens {selectedTech.rx_sensitivity_dbm} dBm
            </span>
          </div>

          {/* ---------------- link budget of the current profile ---------- */}
          {props.study && (
            <div style={{ borderTop: '1px solid var(--hairline)', marginTop: 8, paddingTop: 8 }}>
              <div className="stat-line"><span className="k">{t('study.pathLoss', { model: props.study.technology.model })}</span><span className="v">{props.study.path_loss_db.toFixed(1)} dB</span></div>
              <div className="stat-line"><span className="k">{t('study.diffraction')}<Help term="deygout" /></span><span className="v">{props.study.diffraction_loss_db.toFixed(1)} dB</span></div>
              {(props.study.foliage_loss_db ?? 0) > 0 && (
                <div className="stat-line"><span className="k">{t('study.foliage')}</span><span className="v">{props.study.foliage_loss_db!.toFixed(1)} dB</span></div>
              )}
              {(props.study.rain_loss_db ?? 0) > 0 && (
                <div className="stat-line"><span className="k">{t('study.rain')}</span><span className="v">{props.study.rain_loss_db!.toFixed(1)} dB</span></div>
              )}
              {(props.study.clutter_loss_db ?? 0) > 0 && (
                <div className="stat-line"><span className="k">{t('study.clutterLoss')}</span><span className="v">{props.study.clutter_loss_db!.toFixed(1)} dB</span></div>
              )}
              {(props.study.gaseous_loss_db ?? 0) >= 0.1 && (
                <div className="stat-line"><span className="k">{t('study.gases')}</span><span className="v">{props.study.gaseous_loss_db!.toFixed(1)} dB</span></div>
              )}
              {(props.study.mimo_gain_db ?? 0) > 0 && (
                <div className="stat-line"><span className="k">{t('study.mimoGain')}</span><span className="v">+{props.study.mimo_gain_db!.toFixed(1)} dB</span></div>
              )}
              {props.study.sensitivity_dbm !== undefined && (
                <div className="stat-line"><span className="k">{t('study.sensitivity')}<Help term="sensitivity" /></span><span className="v">{props.study.sensitivity_dbm.toFixed(1)} dBm</span></div>
              )}
              <div className="stat-line"><span className="k">{t('study.rxPower')}</span><span className="v">{props.study.rx_power_dbm.toFixed(1)} dBm</span></div>
              <div className="stat-line">
                <span className="k">{t('study.margin')}</span>
                <span className="v" style={{ color: props.study.served ? 'var(--status-good)' : 'var(--status-critical)' }}>
                  {props.study.margin_db.toFixed(1)} dB {props.study.served ? t('study.served') : t('study.noService')}
                </span>
              </div>
              {props.study.warnings.map((w) => (
                <p key={w} className="hint" style={{ color: 'var(--status-warning)' }}>⚠ {w}</p>
              ))}
            </div>
          )}

          {/* --------------------- area coverage simulation --------------- */}
          <div style={{ borderTop: '1px solid var(--hairline)', marginTop: 8, paddingTop: 8 }}>
            <div className="row">
              <div>
                <label>{t('study.radius')}</label>
                <input type="number" min={1} max={150} value={radiusKm}
                  onChange={(e) => setRadiusKm(parseFloat(e.target.value) || 1)} />
              </div>
              <div>
                <label style={{ marginBottom: 6 }}>{t('study.antenna')}</label>
                <select value={sector ? 'sector' : 'omni'}
                  onChange={(e) => setSector(e.target.value === 'sector')}>
                  <option value="omni">{t('study.omni')}</option>
                  <option value="sector">{t('study.sector')}</option>
                </select>
              </div>
            </div>
            {(sector || antennaId) && (
              <div className="row">
                <div>
                  <label>{t('study.azimuth')}</label>
                  <input type="number" min={0} max={359} value={azimuth}
                    onChange={(e) => setAzimuth(parseFloat(e.target.value) || 0)} />
                </div>
                <div>
                  <label>{t('study.beamwidth')}</label>
                  <input type="number" min={10} max={360} value={beamwidth}
                    onChange={(e) => setBeamwidth(parseFloat(e.target.value) || 65)} />
                </div>
              </div>
            )}
            {/* Measured antenna pattern (MSI Planet). Overrides the
                parametric sector when selected. */}
            <div>
              <label>{t('study.pattern')}</label>
              <select value={antennaId ?? ''} onChange={(e) => setAntennaId(e.target.value || null)}>
                <option value="">{t('study.parametric')}</option>
                {antennas.map((a) => (
                  <option key={a.antenna_id} value={a.antenna_id}>
                    {a.name} — {a.gain_dbi.toFixed(1)} dBi, {a.h_beamwidth_deg}°/{a.v_beamwidth_deg}°
                  </option>
                ))}
              </select>
              <input type="file" accept=".msi,.pln,.ant,.txt" style={{ marginTop: 4 }}
                aria-label="Upload MSI antenna pattern"
                onChange={(e) => e.target.files?.[0] && handleAntennaFile(e.target.files[0])} />
            </div>
            <div className="row">
              <div>
                <label>{t('study.downtilt')}<Help term="downtilt" /></label>
                <input type="number" min={-10} max={20} value={downtilt}
                  onChange={(e) => setDowntilt(parseFloat(e.target.value) || 0)} />
              </div>
              <div>
                <label>{t('study.fadeMargin')}<Help term="fade_margin" /></label>
                <input type="number" min={0} max={30} value={shadowMargin}
                  title="Log-normal shadowing margin: ~5.5 dB ≈ 90% area, ~8 dB ≈ 95%"
                  onChange={(e) => setShadowMargin(parseFloat(e.target.value) || 0)} />
              </div>
            </div>
            <div className="row">
              <div>
                <label>{t('study.foliageDepth')}</label>
                <input type="number" min={0} max={400} value={props.foliageDepth}
                  title="Weissberger vegetation model — dense in-leaf trees at the receiver"
                  onChange={(e) => props.onFoliageChange(parseFloat(e.target.value) || 0)} />
              </div>
              <div>
                <label>{t('study.rainRate')}</label>
                <input type="number" min={0} max={150} value={props.rainRate}
                  title="ITU-R P.838 rain attenuation — matters above ~10 GHz (PtP links)"
                  onChange={(e) => props.onRainChange(parseFloat(e.target.value) || 0)} />
              </div>
            </div>
            <div className="row">
              <div>
                <label>{t('study.clutterPct')}<Help term="clutter" /></label>
                <input type="number" min={0} max={99.9} value={props.clutterPct}
                  title="ITU-R P.2108 statistical urban clutter — 0 = off, 50 = median, 90 = conservative planning"
                  onChange={(e) => props.onClutterChange(parseFloat(e.target.value) || 0)} />
              </div>
              {props.surfaceAvailable && (
                <div>
                  <label>{t('study.surfaceModel')}</label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 400 }}>
                    <input type="checkbox" checked={props.surfaceOn}
                      onChange={(e) => props.onSurfaceChange(e.target.checked)} />
                    {t('study.dsmBuildings')}
                  </label>
                </div>
              )}
            </div>
            <button style={{ width: '100%', marginBottom: 6 }}
              onClick={() => setShowAdvanced((v) => !v)}>
              {showAdvanced ? '▾' : '▸'} {t('study.siteBudget')}
            </button>
            {showAdvanced && (
              <>
                <div className="row">
                  <div>
                    <label>{t('study.txPower')}</label>
                    <input type="number" placeholder={String(selectedTech.tx_power_dbm)}
                      value={ovrPower} onChange={(e) => setOvrPower(e.target.value)} />
                  </div>
                  <div>
                    <label>{t('study.txGain')}</label>
                    <input type="number" placeholder={String(selectedTech.tx_gain_dbi)}
                      value={ovrTxGain} onChange={(e) => setOvrTxGain(e.target.value)} />
                  </div>
                </div>
                <div className="row">
                  <div>
                    <label>{t('study.rxGain')}</label>
                    <input type="number" placeholder={String(selectedTech.rx_gain_dbi)}
                      value={ovrRxGain} onChange={(e) => setOvrRxGain(e.target.value)} />
                  </div>
                  <div>
                    <label>{t('study.losses')}</label>
                    <input type="number" placeholder={String(selectedTech.losses_db)}
                      value={ovrLosses} onChange={(e) => setOvrLosses(e.target.value)} />
                  </div>
                </div>
                <div>
                  <label>{t('study.rxSensitivity')}</label>
                  <input type="number" placeholder={String(selectedTech.rx_sensitivity_dbm)}
                    value={ovrSens} onChange={(e) => setOvrSens(e.target.value)} />
                </div>
              </>
            )}
            <button className="primary" style={{ width: '100%' }} data-tour="coverage"
              disabled={!props.tx || busy} onClick={runCoverage}>
              {busy ? t('study.simulating') : props.tx ? t('study.simulate') : t('study.placeTxFirst')}
            </button>
            {/* ------------------- multi-site best-server study ---------- */}
            <div style={{ borderTop: '1px solid var(--hairline)', marginTop: 8, paddingTop: 8 }}>
              <button style={{ width: '100%' }} disabled={!props.tx}
                onClick={() => props.tx && setSites((prev) => [...prev, {
                  lat: props.tx!.lat, lon: props.tx!.lng,
                  name: `Site ${prev.length + 1}`,
                  antenna_azimuth_deg: sector ? azimuth : null,
                  downtilt_deg: downtilt,
                }])}>
                {t('study.addSite', { count: sites.length })}
              </button>
              {sites.map((s, i) => (
                <div key={i} className="stat-line">
                  <span className="k">{s.name}</span>
                  <span className="v">
                    {s.lat.toFixed(4)}, {s.lon.toFixed(4)}
                    <button style={{ marginLeft: 6, padding: '0 6px' }}
                      aria-label={`Remove ${s.name}`}
                      onClick={() => setSites((prev) => prev.filter((_, j) => j !== i))}>
                      −
                    </button>
                  </span>
                </div>
              ))}
              {sites.length >= 2 && (
                <button className="primary" style={{ width: '100%', marginTop: 4 }}
                  disabled={busy} onClick={runMultiCoverage}>
                  {busy ? t('study.simulating') : t('study.bestServer', { count: sites.length })}
                </button>
              )}
            </div>

            {props.coverage && (
              <>
                {props.coverage.stats.served_area_fraction !== null && (
                  <div className="stat-line" style={{ marginTop: 8 }}>
                    <span className="k">{t('study.servedArea')}</span>
                    <span className="v">{(props.coverage.stats.served_area_fraction * 100).toFixed(0)}%</span>
                  </div>
                )}
                {multiRaw?.sinr && (
                  <>
                    <div className="row" style={{ marginTop: 6 }}>
                      <button className={sinrView ? '' : 'primary'}
                        onClick={() => showMultiView(false)}>{t('study.viewBestServer')}</button>
                      <button className={sinrView ? 'primary' : ''}
                        onClick={() => showMultiView(true)}>{t('study.viewSinr')}</button>
                    </div>
                    <div className="stat-line">
                      <span className="k">{t('study.meanSinr')}</span>
                      <span className="v">{multiRaw.sinr.mean_db.toFixed(1)} dB</span>
                    </div>
                    <div className="stat-line">
                      <span className="k">{t('study.sinrGe6')}</span>
                      <span className="v">{(multiRaw.sinr.ge_6db_fraction * 100).toFixed(0)}%</span>
                    </div>
                    <div className="stat-line">
                      <span className="k">Cell-edge (&lt; 0 dB)</span>
                      <span className="v">{(multiRaw.sinr.edge_fraction * 100).toFixed(0)}% · noise {multiRaw.sinr.noise_dbm.toFixed(0)} dBm</span>
                    </div>
                  </>
                )}
                {props.coverage.stats.sites?.map((s) => (
                  <div key={s.name} className="stat-line">
                    <span className="k">
                      <span style={{ display: 'inline-block', width: 10, height: 10,
                                     borderRadius: 3, background: s.color, marginRight: 5 }} />
                      {s.name}
                    </span>
                    <span className="v">{(s.best_server_share * 100).toFixed(0)}% best server</span>
                  </div>
                ))}
                <div className="stat-line">
                  <span className="k">{t('study.txGround')}</span>
                  <span className="v">{props.coverage.stats.tx_elevation_m.toFixed(0)} m ASL</span>
                </div>
                <div className="stat-line">
                  <span className="k">{t('study.radius')}</span>
                  <span className="v">{(props.coverage.stats.radius_m / 1000).toFixed(0)} km</span>
                </div>
                <div className="stat-line">
                  <span className="k">{t('study.peakRxPower')}</span>
                  <span className="v">{props.coverage.stats.max_rx_power_dbm.toFixed(1)} dBm</span>
                </div>
                <div className="row" style={{ marginTop: 6, flexWrap: 'wrap', gap: 6 }}>
                  <a className="download-link" href={props.coverage.png_url} download>⤓ PNG</a>
                  <a className="download-link"
                    href={props.coverage.png_url.replace(/\.png$/, '.tif')} download
                    title="Georeferenced GeoTIFF (EPSG:4326) for QGIS / ArcGIS / Atoll">
                    ⤓ GeoTIFF
                  </a>
                  <a className="download-link"
                    href={props.coverage.png_url.replace(/\.png$/, '.kmz')} download>
                    ⤓ KMZ (Google Earth)
                  </a>
                </div>
                <div style={{ marginTop: 4 }}>
                  {props.coverage.legend.map((l) => (
                    <div key={l.label} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, padding: '1px 0' }}>
                      <span style={{ width: 12, height: 12, borderRadius: 3, background: l.color, display: 'inline-block' }} />
                      <span style={{ color: 'var(--ink-secondary)' }}>{l.label}</span>
                    </div>
                  ))}
                </div>
                {props.coverage.warnings.map((w) => (
                  <p key={w} className="hint" style={{ color: 'var(--status-warning)' }}>⚠ {w}</p>
                ))}
                <button style={{ width: '100%', marginTop: 6 }}
                  onClick={() => props.onCoverage(null)}>
                  {t('study.clearCoverage')}
                </button>
              </>
            )}
          </div>
        </>
      )}
      {error && <div className="error-box">{error}</div>}
    </div>
  );
}
