'use client';

/**
 * Radio study panel: pick a technology preset (2G GSM ... 5G NR mmWave,
 * PMR, broadcast, Wi-Fi, IoT, microwave PtP), optionally override the
 * propagation model / environment, and run an area coverage simulation from
 * the TX site.  Shows the coverage legend and the point-to-point link budget
 * of the current profile.
 */
import { useEffect, useMemo, useState, useId } from 'react';
import { useTranslation } from 'react-i18next';
import {
  fetchAntennas, fetchEquipment, fetchModels, fetchTechnologies, frequencyPlan,
  CoverageCancelled, friendlyError, monteCarloTraffic, simulateCoverageTracked,
  simulateMultiCoverage,
  throughputMap,
  uploadAntenna,
} from '@/lib/api';
import Help from '@/components/Help';
import type {
  AntennaInfo, CoverageResponse, Equipment, LatLng, ModelInfo, ScenarioResolved,
  SiteEntry, StudyResult,
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
  worldcoverOn: boolean;
  onWorldcoverChange: (v: boolean) => void;
  calibration?: object | null;
  onCalibrationChange?: (c: object | null) => void;
  surfaceAvailable: boolean;
  /** Resolved Simple-mode scenario: its radius / sector / fade-margin are
   *  applied here, because those three live in this panel's own state. */
  scenario?: ScenarioResolved | null;
  /** Guided (Simple) mode: show only what is needed to get an answer --
   *  place the points, run the study, read the result -- and hide every RF
   *  knob.  The scenario has already chosen technology, heights, radius,
   *  sector and fade margin. */
  compact?: boolean;
  study: StudyResult | null;
  coverage: CoverageResponse | null;
  onCoverage: (c: CoverageResponse | null) => void;
}

export default function StudyPanel(props: StudyPanelProps) {
  const _uid = useId();
  const compact = Boolean(props.compact);
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
  // 0..1 while a queued coverage study runs, so a 26 s full-resolution sweep
  // shows real progress instead of a frozen button.
  const [progress, setProgress] = useState(0);
  // Set while a queued study is in flight so the user can stop it.
  const [cancelRun, setCancelRun] = useState<(() => void) | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Spoken status for assistive technology (WCAG 4.1.3). A coverage sweep can
  // take half a minute; without this the user gets no signal that it started,
  // finished, or what it found.
  const [announce, setAnnounce] = useState('');

  // Measured antenna patterns (MSI Planet uploads).
  const [antennas, setAntennas] = useState<AntennaInfo[]>([]);
  const [antennaId, setAntennaId] = useState<string | null>(null);
  // Hardware catalog (Equipment Selector).
  const [equipment, setEquipment] = useState<Equipment[]>([]);
  const [equipmentId, setEquipmentId] = useState<string>('');
  const [freqOverride, setFreqOverride] = useState<number | undefined>(undefined);
  // Multi-site best-server study; the raw response is kept so the map
  // overlay can be flipped between best-server and SINR views.
  const [sites, setSites] = useState<SiteEntry[]>([]);
  const [multiRaw, setMultiRaw] = useState<CoverageResponse | null>(null);
  const [sinrView, setSinrView] = useState(false);
  const [freqPlan, setFreqPlan] = useState<any | null>(null);
  const [planBusy, setPlanBusy] = useState(false);
  const [planChannels, setPlanChannels] = useState(3);
  const [tpRaw, setTpRaw] = useState<any | null>(null);   // /throughput-map result
  const [tpBusy, setTpBusy] = useState(false);
  const [tpView, setTpView] = useState(false);
  const [usersPerCell, setUsersPerCell] = useState('0');
  const [mbpsPerUser, setMbpsPerUser] = useState('0');

  function showMultiView(sinr: boolean) {
    if (!multiRaw) return;
    setSinrView(sinr);
    setTpView(false);
    props.onCoverage(sinr && multiRaw.sinr
      ? { ...multiRaw, png_url: multiRaw.sinr.png_url,
          legend: multiRaw.sinr.legend }
      : multiRaw);
  }

  function showThroughputView() {
    if (!multiRaw || !tpRaw?.png_url) return;
    setSinrView(false);
    setTpView(true);
    props.onCoverage({ ...multiRaw, png_url: tpRaw.png_url,
                       bounds: tpRaw.bounds, legend: tpRaw.legend });
  }

  const numOr = (s: string) => {
    const v = parseFloat(s);
    return Number.isFinite(v) ? v : undefined;
  };

  useEffect(() => {
    fetchTechnologies().then(setTechs).catch(() => setTechs([]));
    fetchModels().then(setModels).catch(() => setModels([]));
    fetchAntennas().then(setAntennas).catch(() => setAntennas([]));
    fetchEquipment().then((r) => setEquipment(r.equipment)).catch(() => setEquipment([]));
  }, []);

  // Apply the resolved Simple-mode scenario's study settings.  radius, sector
  // and fade margin live in this panel's state, so page.tsx cannot set them
  // itself; before this they were simply discarded, and the guided path ran at
  // the default radius with a 0 dB shadow margin -- a 50%-probability median
  // presented to the user least equipped to notice it was optimistic.
  useEffect(() => {
    const s = props.scenario;
    if (!s) return;
    if (typeof s.radius_km === 'number' && s.radius_km > 0) setRadiusKm(s.radius_km);
    if (typeof s.shadow_margin_db === 'number') setShadowMargin(s.shadow_margin_db);
    setSector(Boolean(s.sector));
  }, [props.scenario]);

  /** Drop every link-budget / antenna override back to "use the preset".
   *  Called when the technology changes, so a value left over from a previous
   *  preset or a selected equipment profile can never silently override the
   *  preset the panel is displaying. */
  function clearOverrides() {
    setOvrPower(''); setOvrTxGain(''); setOvrRxGain('');
    setOvrLosses(''); setOvrSens('');
    setAntennaId(null);
    setSector(false); setAzimuth(0); setBeamwidth(65); setDowntilt(0);
  }

  /** Fingerprint of every input the coverage run consumes.
   *
   *  The painted raster, its statistics and its PNG/GeoTIFF/KMZ links used to
   *  be invalidated only when the TX moved or the technology changed, while a
   *  dozen other inputs -- radius, model, environment, TX height, downtilt,
   *  fade margin, clutter, WorldCover, DSM, every budget override -- are sent
   *  to the engine and were not watched.  Raise the mast 20 m -> 40 m and the
   *  live link budget updated while the heatmap, "Served area 62%" and the
   *  export links still described the 20 m run, so the GeoTIFF a user
   *  downloaded as their 40 m design was the wrong study. */
  const runSignature = JSON.stringify([
    props.tx?.lat, props.tx?.lng, props.technology, radiusKm, props.dxfId,
    freqOverride, props.model, props.environment,
    (sector || antennaId) ? azimuth : null, beamwidth, downtilt, antennaId,
    shadowMargin, props.foliageDepth, props.rainRate, props.clutterPct,
    props.surfaceOn, props.worldcoverOn, props.calibration ?? null,
    props.txHeight, ovrPower, ovrTxGain, ovrRxGain, ovrLosses, ovrSens,
  ]);
  // Signature captured when the painted result was produced.
  const [paintedSignature, setPaintedSignature] = useState<string | null>(null);
  const stale = Boolean(props.coverage) && paintedSignature !== null
    && paintedSignature !== runSignature;

  /** Any override currently in force, so the UI can say so instead of
   *  showing the preset's numbers as if they were what will run. */
  const overrideCount = [ovrPower, ovrTxGain, ovrRxGain, ovrLosses, ovrSens]
    .filter((v) => v.trim() !== '').length;

  // Equipment Selector: pick a real hardware profile and auto-fill the RF
  // parameters (technology, model, power, gain, sensitivity, beamwidth,
  // frequency).  Every field remains editable afterwards for advanced users.
  function applyEquipment(id: string) {
    setEquipmentId(id);
    const e = equipment.find((x) => x.id === id);
    if (!e) { setFreqOverride(undefined); return; }
    props.onTechnologyChange(e.technology);
    props.onModelChange(e.model_key ?? null);
    props.onEnvironmentChange(e.environment ?? null);
    setOvrPower(String(e.tx_power_dbm));
    setOvrTxGain(String(e.antenna_gain_dbi));
    setOvrSens(String(e.rx_sensitivity_dbm));
    setFreqOverride(e.freq_mhz);
    const directional = e.beamwidth_deg < 360;
    setSector(directional);
    if (directional) setBeamwidth(e.beamwidth_deg);
  }

  async function handleAntennaFile(file: File) {
    setError(null);
    try {
      const info = await uploadAntenna(file);
      setAntennas((prev) => [...prev, info]);
      setAntennaId(info.antenna_id);
    } catch (e) { setError(friendlyError((e as Error).message)); }
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
        clutterSource: props.worldcoverOn ? 'worldcover' : undefined,
        txPowerDbm: numOr(ovrPower), rxSensitivityDbm: numOr(ovrSens),
      });
      setMultiRaw(resp);
      setSinrView(false);
      setPaintedSignature(runSignature);
      props.onCoverage(resp);
    } catch (e) { setError(friendlyError((e as Error).message)); } finally { setBusy(false); }
  }

  async function runThroughputMap() {
    if (!props.technology || sites.length === 0) return;
    setTpBusy(true);
    setError(null);
    try {
      const resp = await throughputMap({
        sites, technology: props.technology, radius_km: radiusKm,
        users_per_cell: Math.max(0, parseInt(usersPerCell) || 0),
        mbps_per_user: Math.max(0, parseFloat(mbpsPerUser) || 0),
        // Apply the frequency plan's channels when one has been computed.
        channels: freqPlan && freqPlan.assignments?.length === sites.length
          ? freqPlan.assignments.map((a: any) => a.channel) : undefined,
        model: props.model ?? undefined,
        environment: props.environment ?? undefined,
        surface: props.surfaceOn || undefined,
        clutter_source: props.worldcoverOn ? 'worldcover' : undefined,
        h_bs_m: props.txHeight || undefined,
        tx_power_dbm: numOr(ovrPower), tx_gain_dbi: numOr(ovrTxGain),
      });
      setTpRaw(resp);
      if (multiRaw && resp.png_url) {   // switch the map straight to Mbit/s
        setSinrView(false);
        setTpView(true);
        props.onCoverage({ ...multiRaw, png_url: resp.png_url,
                           bounds: resp.bounds, legend: resp.legend });
      }
    } catch (e) { setError(friendlyError((e as Error).message)); } finally { setTpBusy(false); }
  }

  const [mcRaw, setMcRaw] = useState<any | null>(null);
  const [mcBusy, setMcBusy] = useState(false);

  async function runMonteCarlo() {
    if (!props.technology || sites.length === 0) return;
    setMcBusy(true);
    setError(null);
    try {
      const resp = await monteCarloTraffic({
        sites, technology: props.technology, radius_km: radiusKm,
        users: Math.max(1, parseInt(usersPerCell) * sites.length || 100),
        demand_mbps: Math.max(0.1, parseFloat(mbpsPerUser) || 1),
        draws: 100, render: false,
        channels: freqPlan && freqPlan.assignments?.length === sites.length
          ? freqPlan.assignments.map((a: any) => a.channel) : undefined,
        model: props.model ?? undefined,
        environment: props.environment ?? undefined,
        surface: props.surfaceOn || undefined,
        clutter_source: props.worldcoverOn ? 'worldcover' : undefined,
        h_bs_m: props.txHeight || undefined,
        tx_power_dbm: numOr(ovrPower), tx_gain_dbi: numOr(ovrTxGain),
      });
      setMcRaw(resp);
    } catch (e) { setError(friendlyError((e as Error).message)); } finally { setMcBusy(false); }
  }

  async function runFrequencyPlan() {
    if (!props.technology || sites.length < 2) return;
    setPlanBusy(true);
    setError(null);
    try {
      const resp = await frequencyPlan({
        sites, technology: props.technology, radius_km: radiusKm,
        n_channels: planChannels,
        model: props.model ?? undefined,
        environment: props.environment ?? undefined,
        surface: props.surfaceOn || undefined,
        clutter_source: props.worldcoverOn ? 'worldcover' : undefined,
        h_bs_m: props.txHeight || undefined,
        tx_power_dbm: numOr(ovrPower), tx_gain_dbi: numOr(ovrTxGain),
      });
      setFreqPlan(resp);
    } catch (e) { setError(friendlyError((e as Error).message)); } finally { setPlanBusy(false); }
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
    setProgress(0);
    setError(null);
    setAnnounce(t('study.a11yStarted'));
    try {
      const resp = await simulateCoverageTracked({
        lat: props.tx.lat, lon: props.tx.lng,
        technology: props.technology, radiusKm,
        dxfId: props.dxfId,
        freqMhz: freqOverride,
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
        clutterSource: props.worldcoverOn ? 'worldcover' : undefined,
        calibration: props.calibration ?? undefined,
        hBsM: props.txHeight || undefined,
        txPowerDbm: numOr(ovrPower), txGainDbi: numOr(ovrTxGain),
        rxGainDbi: numOr(ovrRxGain), lossesDb: numOr(ovrLosses),
        rxSensitivityDbm: numOr(ovrSens),
      }, setProgress, (cancel) => setCancelRun(() => cancel));
      setMultiRaw(null);
      setSinrView(false);
      setPaintedSignature(runSignature);
      props.onCoverage(resp);
      const served = resp?.stats?.served_area_fraction;
      const peak = resp?.stats?.max_rx_power_dbm;
      setAnnounce(t('study.a11yDone', {
        served: served != null ? Math.round(served * 100) : '—',
        peak: peak != null ? peak.toFixed(0) : '—',
      }));
    } catch (e) {
      // Stopping your own study is an expected outcome, not an error.
      if (!(e instanceof CoverageCancelled)) {
        const msg = friendlyError((e as Error).message);
        setError(msg);
        setAnnounce(msg);
      } else {
        setAnnounce(t('study.a11yCancelled'));
      }
    } finally {
      setBusy(false);
      setProgress(0);
      setCancelRun(null);
    }
  }

  const equipGroups = useMemo(() => {
    const g = new Map<string, Equipment[]>();
    for (const e of equipment) {
      if (!g.has(e.category)) g.set(e.category, []);
      g.get(e.category)!.push(e);
    }
    return Array.from(g.entries());
  }, [equipment]);

  return (
    <div className="panel">
      <h3 data-tour="technology">{t('study.title')}</h3>
      {/* Polite live region: start / completion / failure of a study is spoken,
          so a screen-reader user is not left waiting in silence. */}
      <div role="status" aria-live="polite" className="sr-only"
        data-testid="study-status">{announce}</div>

      {/* Equipment Selector — pick real gear; it auto-fills the RF settings,
          all of which stay editable below. */}
      {!compact && equipment.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <label htmlFor={`${_uid}-0`}>{t('study.equipment')}<Help term="gain" /></label>
          <select id={`${_uid}-0`} value={equipmentId} onChange={(e) => applyEquipment(e.target.value)}>
            <option value="">{t('study.equipmentNone')}</option>
            {equipGroups.map(([cat, list]) => (
              <optgroup key={cat} label={cat}>
                {list.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.model} — {e.band_label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          {equipmentId && (
            <p className="hint">{t('study.equipmentApplied')}</p>
          )}
        </div>
      )}

      {!compact && (<>
      <label htmlFor={`${_uid}-1`}>{t('study.technology')}</label>
      <select id={`${_uid}-1`}
        value={props.technology ?? ''}
        onChange={(e) => {
          props.onTechnologyChange(e.target.value || null);
          props.onModelChange(null);
          props.onEnvironmentChange(null);
          setEquipmentId(''); setFreqOverride(undefined);
          // Clear everything the Equipment Selector or the site-budget panel
          // wrote.  These used to survive a preset change while the "Preset"
          // readout showed the NEW technology's figures, so picking a Wi-Fi AP
          // and then switching to TETRA displayed 40 dBm / -103 dBm omni while
          // actually running 23 dBm / -82 dBm inside a 65-degree sector -- a
          // ~38 dB error with nothing on screen contradicting it, because the
          // override fields are collapsed out of sight by default.
          clearOverrides();
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
      </>)}

      {selectedTech && (
        <>
          {!compact && (<>
          <div className="row" style={{ marginTop: 8 }}>
            <div>
              <label htmlFor={`${_uid}-2`}>{t('study.model')}</label>
              <select id={`${_uid}-2`}
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
              <label htmlFor={`${_uid}-3`}>{t('study.environment')}</label>
              <select id={`${_uid}-3`}
                value={props.environment ?? selectedTech.environment}
                onChange={(e) => props.onEnvironmentChange(e.target.value)}
              >
                {activeModel.environments.map((env) => (
                  <option key={env} value={env}>{env}</option>
                ))}
              </select>
            </div>
          )}
          {/* Show what will ACTUALLY run.  Reading the preset's figures while
              a collapsed override silently replaces them is how a study ends
              up 38 dB out with nothing on screen to contradict it. */}
          <div className="stat-line" style={{ marginTop: 6 }}>
            <span className="k">
              {overrideCount > 0 ? t('study.effective') : t('study.preset')}
            </span>
            <span className="v" data-testid="effective-budget">
              {(freqOverride ?? selectedTech.freq_mhz).toLocaleString()} MHz ·
              TX {numOr(ovrPower) ?? selectedTech.tx_power_dbm} dBm ·
              sens {numOr(ovrSens) ?? selectedTech.rx_sensitivity_dbm} dBm
              {sector && ` · ${beamwidth}° @ ${azimuth}°`}
            </span>
          </div>
          </>)}

          {/* ---------------- link budget of the current profile ---------- */}
          {!compact && props.study && (
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
                <label htmlFor={`${_uid}-4`}>{t('study.radius')}</label>
                <input id={`${_uid}-4`} type="number" min={1} max={150} value={radiusKm}
                  onChange={(e) => setRadiusKm(parseFloat(e.target.value) || 1)} />
              </div>
              {!compact && (
              <div>
                <label htmlFor={`${_uid}-5`} style={{ marginBottom: 6 }}>{t('study.antenna')}</label>
                <select id={`${_uid}-5`} value={sector ? 'sector' : 'omni'}
                  onChange={(e) => setSector(e.target.value === 'sector')}>
                  <option value="omni">{t('study.omni')}</option>
                  <option value="sector">{t('study.sector')}</option>
                </select>
              </div>
              )}
            </div>
            {!compact && (<>
            {(sector || antennaId) && (
              <div className="row">
                <div>
                  <label htmlFor={`${_uid}-6`}>{t('study.azimuth')}</label>
                  <input id={`${_uid}-6`} type="number" min={0} max={359} value={azimuth}
                    onChange={(e) => setAzimuth(parseFloat(e.target.value) || 0)} />
                </div>
                <div>
                  <label htmlFor={`${_uid}-7`}>{t('study.beamwidth')}</label>
                  <input id={`${_uid}-7`} type="number" min={10} max={360} value={beamwidth}
                    onChange={(e) => setBeamwidth(parseFloat(e.target.value) || 65)} />
                </div>
              </div>
            )}
            {/* Measured antenna pattern (MSI Planet). Overrides the
                parametric sector when selected. */}
            <div>
              <label htmlFor={`${_uid}-8`}>{t('study.pattern')}</label>
              <select id={`${_uid}-8`} value={antennaId ?? ''} onChange={(e) => setAntennaId(e.target.value || null)}>
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
                <label htmlFor={`${_uid}-9`}>{t('study.downtilt')}<Help term="downtilt" /></label>
                <input id={`${_uid}-9`} type="number" min={-10} max={20} value={downtilt}
                  onChange={(e) => setDowntilt(parseFloat(e.target.value) || 0)} />
              </div>
              <div>
                <label htmlFor={`${_uid}-10`}>{t('study.fadeMargin')}<Help term="fade_margin" /></label>
                <input id={`${_uid}-10`} type="number" min={0} max={30} value={shadowMargin}
                  title="Log-normal shadowing margin: ~5.5 dB ≈ 90% area, ~8 dB ≈ 95%"
                  onChange={(e) => setShadowMargin(parseFloat(e.target.value) || 0)} />
              </div>
            </div>
            <div className="row">
              <div>
                <label htmlFor={`${_uid}-11`}>{t('study.foliageDepth')}</label>
                <input id={`${_uid}-11`} type="number" min={0} max={400} value={props.foliageDepth}
                  title="Weissberger vegetation model — dense in-leaf trees at the receiver"
                  onChange={(e) => props.onFoliageChange(parseFloat(e.target.value) || 0)} />
              </div>
              <div>
                <label htmlFor={`${_uid}-12`}>{t('study.rainRate')}</label>
                <input id={`${_uid}-12`} type="number" min={0} max={150} value={props.rainRate}
                  title="ITU-R P.838 rain attenuation — matters above ~10 GHz (PtP links)"
                  onChange={(e) => props.onRainChange(parseFloat(e.target.value) || 0)} />
              </div>
            </div>
            <div className="row">
              <div>
                <label htmlFor={`${_uid}-13`}>{t('study.clutterPct')}<Help term="clutter" /></label>
                <input id={`${_uid}-13`} type="number" min={0} max={99.9} value={props.clutterPct}
                  title="ITU-R P.2108 statistical urban clutter — 0 = off, 50 = median, 90 = conservative planning"
                  onChange={(e) => props.onClutterChange(parseFloat(e.target.value) || 0)} />
              </div>
              <div>
                <label>{t('study.worldcover')}</label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 400 }}
                  title="ESA WorldCover 10 m land cover — per-pixel P.1812 representative clutter heights (trees 15 m, built-up 10 m) applied to the terrain profile. Needs internet on first use; tiles are cached.">
                  <input type="checkbox" checked={props.worldcoverOn}
                    onChange={(e) => props.onWorldcoverChange(e.target.checked)} />
                  {t('study.worldcoverLabel')}
                </label>
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
              {/* A badge so an override hidden behind a collapsed section is
                  still visible from the outside. */}
              {overrideCount > 0 && (
                <span className="arrange-badge" data-testid="override-count"
                  title={t('study.overridesActive', { count: overrideCount })}>
                  {overrideCount}
                </span>
              )}
            </button>
            {showAdvanced && (
              <>
                <div className="row">
                  <div>
                    <label htmlFor={`${_uid}-14`}>{t('study.txPower')}</label>
                    <input id={`${_uid}-14`} type="number" placeholder={String(selectedTech.tx_power_dbm)}
                      value={ovrPower} onChange={(e) => setOvrPower(e.target.value)} />
                  </div>
                  <div>
                    <label htmlFor={`${_uid}-15`}>{t('study.txGain')}</label>
                    <input id={`${_uid}-15`} type="number" placeholder={String(selectedTech.tx_gain_dbi)}
                      value={ovrTxGain} onChange={(e) => setOvrTxGain(e.target.value)} />
                  </div>
                </div>
                <div className="row">
                  <div>
                    <label htmlFor={`${_uid}-16`}>{t('study.rxGain')}</label>
                    <input id={`${_uid}-16`} type="number" placeholder={String(selectedTech.rx_gain_dbi)}
                      value={ovrRxGain} onChange={(e) => setOvrRxGain(e.target.value)} />
                  </div>
                  <div>
                    <label htmlFor={`${_uid}-17`}>{t('study.losses')}</label>
                    <input id={`${_uid}-17`} type="number" placeholder={String(selectedTech.losses_db)}
                      value={ovrLosses} onChange={(e) => setOvrLosses(e.target.value)} />
                  </div>
                </div>
                <div>
                  <label htmlFor={`${_uid}-18`}>{t('study.rxSensitivity')}</label>
                  <input id={`${_uid}-18`} type="number" placeholder={String(selectedTech.rx_sensitivity_dbm)}
                    value={ovrSens} onChange={(e) => setOvrSens(e.target.value)} />
                </div>
              </>
            )}
            </>)}
            <button className="primary" style={{ width: '100%' }} data-tour="coverage"
              disabled={!props.tx || busy} onClick={runCoverage}>
              {busy
                ? `${t('study.simulating')} ${(progress * 100).toFixed(0)}%`
                : props.tx ? t('study.simulate') : t('study.placeTxFirst')}
            </button>
            {busy && (
              /* Live progress for the queued study: a full-resolution sweep is
                 ~26 s of compute, which is far too long for a static label. */
              <div className="progress" role="progressbar" aria-label={t('study.simulating')}
                aria-valuemin={0} aria-valuemax={100}
                aria-valuenow={Math.round(progress * 100)}>
                <div className="progress-fill" style={{ width: `${progress * 100}%` }} />
              </div>
            )}
            {busy && cancelRun && (
              <button style={{ width: '100%', marginTop: 4 }}
                onClick={() => { cancelRun(); setCancelRun(null); }}>
                {t('study.cancel')}
              </button>
            )}
            {/* ------------------- multi-site best-server study ---------- */}
            {!compact && (
            <div style={{ borderTop: '1px solid var(--hairline)', marginTop: 8, paddingTop: 8 }}>
              <button style={{ width: '100%' }} disabled={!props.tx}
                onClick={() => props.tx && (setFreqPlan(null), setTpRaw(null), setMcRaw(null),
                  setSites((prev) => [...prev, {
                    lat: props.tx!.lat, lon: props.tx!.lng,
                    name: `Site ${prev.length + 1}`,
                    antenna_azimuth_deg: sector ? azimuth : null,
                    downtilt_deg: downtilt,
                  }]))}>
                {t('study.addSite', { count: sites.length })}
              </button>
              {sites.map((s, i) => (
                <div key={i} className="stat-line">
                  <span className="k">{s.name}</span>
                  <span className="v">
                    {s.lat.toFixed(4)}, {s.lon.toFixed(4)}
                    <button style={{ marginLeft: 6, padding: '0 6px' }}
                      aria-label={`Remove ${s.name}`}
                      onClick={() => { setFreqPlan(null); setTpRaw(null); setMcRaw(null);
                        setSites((prev) => prev.filter((_, j) => j !== i)); }}>
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
              {/* ---------------- automatic frequency / PCI plan ---------- */}
              {sites.length >= 2 && sites.length <= 24 && (
                <>
                  <div className="row" style={{ marginTop: 4, alignItems: 'flex-end' }}>
                    <div>
                      <label htmlFor={`${_uid}-19`}>{t('study.planChannels')}</label>
                      <input id={`${_uid}-19`} type="number" min={2} max={12} value={planChannels}
                        onChange={(e) => setPlanChannels(Math.min(12, Math.max(2, parseInt(e.target.value) || 3)))} />
                    </div>
                    <button style={{ flex: 1 }} disabled={planBusy}
                      title="Interference-matrix graph colouring: channel + PCI per site, with the SINR gain vs reuse-1 measured on the same grid"
                      onClick={runFrequencyPlan}>
                      {planBusy ? t('study.simulating') : t('study.freqPlan')}
                    </button>
                  </div>
                  {freqPlan && (
                    <div style={{ marginTop: 4 }}>
                      {freqPlan.assignments?.map((a: any) => (
                        <div key={a.site} className="stat-line">
                          <span className="k">{a.site}</span>
                          <span className="v">
                            {t('study.channel')} {a.channel + 1}
                            {a.pci !== undefined && <> · PCI {a.pci} (mod3 {a.pci_mod3})</>}
                          </span>
                        </div>
                      ))}
                      <div className="stat-line">
                        <span className="k">{t('study.sinrBaseline')}</span>
                        <span className="v">
                          {freqPlan.sinr_reuse1_baseline?.mean_sinr_db ?? '—'} dB →{' '}
                          <b>{freqPlan.sinr_after_plan?.mean_sinr_db ?? '—'} dB</b>
                          {freqPlan.gain_mean_sinr_db !== null && freqPlan.gain_mean_sinr_db !== undefined && (
                            <> ({freqPlan.gain_mean_sinr_db >= 0 ? '+' : ''}{freqPlan.gain_mean_sinr_db} dB)</>
                          )}
                        </span>
                      </div>
                      <button style={{ width: '100%', marginTop: 2 }} onClick={() => setFreqPlan(null)}>
                        {t('study.clearPlan')}
                      </button>
                    </div>
                  )}
                  {/* -------------- capacity / throughput map ------------- */}
                  <div className="row" style={{ marginTop: 4, alignItems: 'flex-end' }}>
                    <div>
                      <label htmlFor={`${_uid}-20`}>{t('study.usersPerCell')}</label>
                      <input id={`${_uid}-20`} type="number" min={0} value={usersPerCell}
                        onChange={(e) => setUsersPerCell(e.target.value)} />
                    </div>
                    <div>
                      <label htmlFor={`${_uid}-21`}>{t('study.mbpsPerUser')}</label>
                      <input id={`${_uid}-21`} type="number" min={0} step={0.1} value={mbpsPerUser}
                        onChange={(e) => setMbpsPerUser(e.target.value)} />
                    </div>
                    <button style={{ flex: 1 }} disabled={tpBusy}
                      title="Per-cell capacity from the SINR field via the 3GPP CQI ladder + Mbit/s heatmap; applies the frequency plan's channels when one is computed"
                      onClick={runThroughputMap}>
                      {tpBusy ? t('study.simulating') : t('study.throughputMap')}
                    </button>
                  </div>
                  {tpRaw && (
                    <div style={{ marginTop: 4 }}>
                      {tpRaw.cells?.map((cell: any) => (
                        <div key={cell.site} className="stat-line">
                          <span className="k">{cell.site}</span>
                          <span className="v">
                            {cell.capacity_mbps} Mbit/s
                            {cell.saturation && (
                              <> · {cell.saturation.saturated
                                ? <b style={{ color: 'var(--status-error, #c0392b)' }}>
                                    {t('study.saturated')} ({cell.saturation.load_factor}×)
                                  </b>
                                : <>{t('study.headroom')} {cell.saturation.max_users} {t('study.users')}</>}
                              </>
                            )}
                          </span>
                        </div>
                      ))}
                      <div className="stat-line">
                        <span className="k">{t('study.planApplied')}</span>
                        <span className="v">{tpRaw.plan_applied ? '✓' : t('study.reuse1')}</span>
                      </div>
                      {tpRaw.png_url && !tpView && multiRaw && (
                        <button style={{ width: '100%', marginTop: 2 }} onClick={showThroughputView}>
                          {t('study.viewMbps')}
                        </button>
                      )}
                    </div>
                  )}
                  {/* ------------- Monte Carlo traffic snapshots ---------- */}
                  <button style={{ width: '100%', marginTop: 4 }} disabled={mcBusy}
                    title="100 random user-drop snapshots over the served area (uses the Users/cell × Mbit/s demand above; applies the frequency plan when computed): satisfied-user fraction with confidence bounds"
                    onClick={runMonteCarlo}>
                    {mcBusy ? t('study.simulating') : t('study.monteCarlo')}
                  </button>
                  {mcRaw && (
                    <div style={{ marginTop: 4 }}>
                      <div className="stat-line">
                        <span className="k">{t('study.mcSatisfied')}</span>
                        <span className="v">
                          <b>{(mcRaw.satisfied_fraction.mean * 100).toFixed(1)}%</b>
                          {' '}(p5 {(mcRaw.satisfied_fraction.p5 * 100).toFixed(1)}% · p95 {(mcRaw.satisfied_fraction.p95 * 100).toFixed(1)}%)
                        </span>
                      </div>
                      <div className="stat-line">
                        <span className="k">{t('study.mcEdgeRate')}</span>
                        <span className="v">{mcRaw.user_rate_p5_mbps.mean} Mbit/s</span>
                      </div>
                      {mcRaw.cells.map((c: any) => (
                        <div key={c.site} className="stat-line">
                          <span className="k">{c.site}</span>
                          <span className="v">
                            {c.mean_users} {t('study.users')}
                            {c.mean_satisfied_fraction !== null &&
                              <> · {(c.mean_satisfied_fraction * 100).toFixed(0)}% {t('study.mcOk')}</>}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
            )}

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
                      <button className={!sinrView && !tpView ? 'primary' : ''}
                        onClick={() => showMultiView(false)}>{t('study.viewBestServer')}</button>
                      <button className={sinrView ? 'primary' : ''}
                        onClick={() => showMultiView(true)}>{t('study.viewSinr')}</button>
                      {tpRaw?.png_url && (
                        <button className={tpView ? 'primary' : ''}
                          onClick={showThroughputView}>{t('study.viewMbps')}</button>
                      )}
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
                {/* A result whose inputs have since changed must not be
                    exportable: the whole failure mode is a user downloading a
                    GeoTIFF as "the 40 m design" when it is the 20 m run. */}
                {stale && (
                  <div className="warning-box" role="status" data-testid="stale-coverage"
                    style={{ marginTop: 6 }}>
                    ⚠ {t('study.staleResult')}
                  </div>
                )}
                <div className="row" style={{ marginTop: 6, flexWrap: 'wrap', gap: 6 }}>
                  {stale ? (
                    <span className="hint" data-testid="stale-exports">
                      {t('study.staleExports')}
                    </span>
                  ) : (<>
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
                  </>)}
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
      {error && <div className="error-box" role="alert">{error}</div>}
    </div>
  );
}
