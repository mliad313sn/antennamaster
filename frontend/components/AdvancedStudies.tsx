'use client';

/**
 * Advanced studies modal — the Layer-2..5 capabilities added to the platform:
 *
 *  1. Two-way (LMR) talk-back: talk-out AND talk-in with DAQ grading and the
 *     limiting direction — the question every public-safety/mining tender asks.
 *  2. EMF compliance: ICNIRP / FCC OET-65 exposure exclusion-zone distances.
 *  3. ITM (Longley-Rice): irregular-terrain path loss with a reliability
 *     quantile — the statistical model empirical curves cannot give.
 *  4. Copilot: engine-driven diagnosis with quantified, actionable fixes.
 *
 * Link-based tabs use the TX/RX markers already placed on the map.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDialog } from '@/lib/useDialog';
import {
  availabilityStudy, calibrateDriveTest, copilotAnalyzeLink, emfCompliance,
  emfReportPdf, erlangStudy, itmStudy, p1812Study, p2001Study, p452Study,
  twowayLink,
} from '@/lib/api';

type LatLng = { lat: number; lng: number };
type Tab = 'twoway' | 'emf' | 'itm' | 'p1812' | 'p452' | 'p2001' | 'avail' | 'erlang' | 'calib' | 'copilot';

export default function AdvancedStudies(
  { tx, rx, technology, onClose, calibration, onCalibration }:
  { tx: LatLng | null; rx: LatLng | null; technology: string | null;
    onClose: () => void;
    calibration?: object | null; onCalibration?: (c: object | null) => void },
) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>('twoway');
  const dialogRef = useDialog(onClose);
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" style={{ width: 820 }} onClick={(e) => e.stopPropagation()}
        role="dialog" aria-modal="true" aria-labelledby="advanced-title"
        ref={dialogRef} tabIndex={-1}>
        <div className="modal-head">
          <h2 id="advanced-title">{t('advanced.title')}</h2>
          <button onClick={onClose} aria-label={t('advanced.close')}>✕</button>
        </div>
        <div className="modal-body">
          <div className="mode-tabs">
            <button className={tab === 'twoway' ? 'active' : ''} aria-pressed={tab === 'twoway'} onClick={() => setTab('twoway')}>{t('advanced.tabTwoway')}</button>
            <button className={tab === 'emf' ? 'active' : ''} aria-pressed={tab === 'emf'} onClick={() => setTab('emf')}>{t('advanced.tabEmf')}</button>
            <button className={tab === 'itm' ? 'active' : ''} aria-pressed={tab === 'itm'} onClick={() => setTab('itm')}>{t('advanced.tabItm')}</button>
            <button className={tab === 'p1812' ? 'active' : ''} aria-pressed={tab === 'p1812'} onClick={() => setTab('p1812')}>{t('advanced.tabP1812')}</button>
            <button className={tab === 'p452' ? 'active' : ''} aria-pressed={tab === 'p452'} onClick={() => setTab('p452')}>{t('advanced.tabP452')}</button>
            <button className={tab === 'p2001' ? 'active' : ''} aria-pressed={tab === 'p2001'} onClick={() => setTab('p2001')}>{t('advanced.tabP2001')}</button>
            <button className={tab === 'avail' ? 'active' : ''} aria-pressed={tab === 'avail'} onClick={() => setTab('avail')}>{t('advanced.tabAvail')}</button>
            <button className={tab === 'erlang' ? 'active' : ''} aria-pressed={tab === 'erlang'} onClick={() => setTab('erlang')}>{t('advanced.tabErlang')}</button>
            <button className={tab === 'calib' ? 'active' : ''} aria-pressed={tab === 'calib'} onClick={() => setTab('calib')}>{t('advanced.tabCalib')}</button>
            <button className={tab === 'copilot' ? 'active' : ''} aria-pressed={tab === 'copilot'} onClick={() => setTab('copilot')}>{t('advanced.tabCopilot')}</button>
          </div>
          {tab === 'twoway' && <TwoWayTab tx={tx} rx={rx} />}
          {tab === 'emf' && <EmfTab />}
          {tab === 'itm' && <ItmTab tx={tx} rx={rx} />}
          {tab === 'p1812' && <P1812Tab tx={tx} rx={rx} />}
          {tab === 'p452' && <P452Tab tx={tx} rx={rx} />}
          {tab === 'p2001' && <P2001Tab tx={tx} rx={rx} />}
          {tab === 'avail' && <AvailTab tx={tx} rx={rx} />}
          {tab === 'erlang' && <ErlangTab />}
          {tab === 'calib' && (
            <CalibTab tx={tx} technology={technology}
              calibration={calibration ?? null}
              onCalibration={onCalibration ?? (() => {})} />
          )}
          {tab === 'copilot' && <CopilotTab tx={tx} rx={rx} technology={technology} />}
        </div>
      </div>
    </div>
  );
}

function useRun<T>() {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<T | null>(null);
  const run = async (fn: () => Promise<T>) => {
    setBusy(true); setErr(null);
    try { setRes(await fn()); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  return { busy, err, res, run };
}

function NeedMarkers({ tx, rx }: { tx: LatLng | null; rx: LatLng | null }) {
  const { t } = useTranslation();
  if (tx && rx) return null;
  return <p className="hint">{t('advanced.needMarkers')}</p>;
}

// ---------------------------------------------------------------- two-way
function TwoWayTab({ tx, rx }: { tx: LatLng | null; rx: LatLng | null }) {
  const { t } = useTranslation();
  const [freq, setFreq] = useState('155');
  const [basePower, setBasePower] = useState('44');
  const [portPower, setPortPower] = useState('37');
  const [pen, setPen] = useState('on_street');
  const { busy, err, res, run } = useRun<any>();
  const go = () => tx && rx && run(() => twowayLink({
    base: { freq_mhz: +freq, model: 'okumura_hata', environment: 'suburban',
            h_bs_m: 40, tx_power_dbm: +basePower, ant_gain_dbi: 6,
            rx_sensitivity_dbm: -119, losses_db: 3 },
    portable: { tx_power_dbm: +portPower, ant_gain_dbi: 0,
                rx_sensitivity_dbm: -119, h_ut_m: 1.5, penetration_class: pen },
    tx_lat: tx.lat, tx_lon: tx.lng, rx_lat: rx.lat, rx_lon: rx.lng,
  }));
  return (
    <div>
      <p className="hint">{t('advanced.twowayHint')}</p>
      <NeedMarkers tx={tx} rx={rx} />
      <div className="field-grid">
        <label>{t('advanced.freqMhz')}<input value={freq} onChange={(e) => setFreq(e.target.value)} /></label>
        <label>{t('advanced.basePower')}<input value={basePower} onChange={(e) => setBasePower(e.target.value)} /></label>
        <label>{t('advanced.portPower')}<input value={portPower} onChange={(e) => setPortPower(e.target.value)} /></label>
        <label>{t('advanced.penetration')}
          <select value={pen} onChange={(e) => setPen(e.target.value)}>
            <option value="on_street">{t('advanced.penStreet')}</option>
            <option value="in_vehicle">{t('advanced.penVehicle')}</option>
            <option value="light_building">{t('advanced.penLight')}</option>
            <option value="heavy_building">{t('advanced.penHeavy')}</option>
          </select>
        </label>
      </div>
      <button className="primary" style={{ width: '100%' }} disabled={!tx || !rx || busy} onClick={go}>
        {busy ? t('advanced.running') : t('advanced.run')}
      </button>
      {err && <div className="warning-box" role="status">{err}</div>}
      {res && (
        <table className="result-table">
          <tbody>
            <tr><td>{t('advanced.talkOut')}</td><td>{res.talk_out.rx_power_dbm} dBm · {res.talk_out.label}</td></tr>
            <tr><td>{t('advanced.talkIn')}</td><td>{res.talk_in.rx_power_dbm} dBm · {res.talk_in.label}</td></tr>
            <tr><td>{t('advanced.limiting')}</td><td>{t(res.limiting_direction === 'talk_in' ? 'advanced.talkIn' : 'advanced.talkOut')}</td></tr>
            <tr><td>{t('advanced.reliable')}</td><td>{res.reliable ? '✓' : '✗'} (DAQ {res.worst_daq})</td></tr>
          </tbody>
        </table>
      )}
    </div>
  );
}

// -------------------------------------------------------------------- EMF
function EmfTab() {
  const { t } = useTranslation();
  const [freq, setFreq] = useState('900');
  const [power, setPower] = useState('43');
  const [gain, setGain] = useState('15');
  const [losses, setLosses] = useState('0');
  const [std, setStd] = useState('icnirp');
  const { busy, err, res, run } = useRun<any>();
  const [pdfBusy, setPdfBusy] = useState(false);
  const go = () => run(() => emfCompliance({
    freq_mhz: +freq, tx_power_dbm: +power, antenna_gain_dbi: +gain,
    losses_db: +losses, standard: std,
  }));
  const [pdfErr, setPdfErr] = useState<string | null>(null);
  const downloadPdf = async () => {
    setPdfBusy(true);
    setPdfErr(null);
    try {
      const blob = await emfReportPdf({
        site: { name: 'AntennaMaster site' },
        antennas: [{ label: 'Antenna 1', freq_mhz: +freq, tx_power_dbm: +power,
                     antenna_gain_dbi: +gain, losses_db: +losses }],
        standard: std,
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'emf-compliance.pdf';
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setPdfErr(e instanceof Error ? e.message : String(e));
    } finally {
      setPdfBusy(false);
    }
  };
  return (
    <div>
      <p className="hint">{t('advanced.emfHint')}</p>
      <div className="field-grid">
        <label>{t('advanced.freqMhz')}<input value={freq} onChange={(e) => setFreq(e.target.value)} /></label>
        <label>{t('advanced.txPower')}<input value={power} onChange={(e) => setPower(e.target.value)} /></label>
        <label>{t('advanced.antGain')}<input value={gain} onChange={(e) => setGain(e.target.value)} /></label>
        <label>{t('advanced.feederLoss')}<input value={losses} onChange={(e) => setLosses(e.target.value)} /></label>
        <label>{t('advanced.standard')}
          <select value={std} onChange={(e) => setStd(e.target.value)}>
            <option value="icnirp">ICNIRP</option>
            <option value="fcc">FCC OET-65</option>
          </select>
        </label>
      </div>
      <button className="primary" style={{ width: '100%' }} disabled={busy} onClick={go}>
        {busy ? t('advanced.running') : t('advanced.run')}
      </button>
      {err && <div className="warning-box" role="status">{err}</div>}
      {res && (
        <table className="result-table">
          <tbody>
            <tr><td>{t('advanced.eirp')}</td><td>{res.eirp_dbm} dBm ({res.eirp_w} W)</td></tr>
            <tr><td>{t('advanced.publicZone')}</td><td>{res.public_compliance_distance_m} m</td></tr>
            <tr><td>{t('advanced.occZone')}</td><td>{res.occupational_compliance_distance_m} m</td></tr>
          </tbody>
        </table>
      )}
      {res && (
        <button style={{ width: '100%', marginTop: 8 }} disabled={pdfBusy} onClick={downloadPdf}>
          {pdfBusy ? t('advanced.running') : t('advanced.emfPdf')}
        </button>
      )}
      {pdfErr && <div className="warning-box" role="status">{pdfErr}</div>}
    </div>
  );
}

// -------------------------------------------------------------------- ITM
const ITM_CLIMATES = [
  [1, 'Equatorial'], [2, 'Continental subtropical'], [3, 'Maritime subtropical'],
  [4, 'Desert'], [5, 'Continental temperate'],
  [6, 'Maritime temperate (land)'], [7, 'Maritime temperate (sea)'],
] as const;

function ItmTab({ tx, rx }: { tx: LatLng | null; rx: LatLng | null }) {
  const { t } = useTranslation();
  const [freq, setFreq] = useState('900');
  const [rel, setRel] = useState('0.9');
  const [climate, setClimate] = useState('5');
  const [en0, setEn0] = useState('314');
  const [htx, setHtx] = useState('30');
  const [hrx, setHrx] = useState('10');
  const { busy, err, res, run } = useRun<any>();
  const go = () => tx && rx && run(() => itmStudy({
    lat1: tx.lat, lon1: tx.lng, lat2: rx.lat, lon2: rx.lng,
    freq_mhz: +freq, reliability: +rel, confidence: 0.5,
    climate: +climate, en0: +en0, h_tx_m: +htx, h_rx_m: +hrx,
  }));
  return (
    <div>
      <p className="hint">{t('advanced.itmHint')}</p>
      <NeedMarkers tx={tx} rx={rx} />
      <div className="field-grid">
        <label>{t('advanced.freqMhz')}<input value={freq} onChange={(e) => setFreq(e.target.value)} /></label>
        <label>{t('advanced.reliability')}<input value={rel} onChange={(e) => setRel(e.target.value)} /></label>
        <label>{t('advanced.climate')}
          <select value={climate} onChange={(e) => setClimate(e.target.value)}>
            {ITM_CLIMATES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
        </label>
        <label>{t('advanced.en0')}<input value={en0} onChange={(e) => setEn0(e.target.value)}
          title="Surface refractivity N₀ in N-units (world median 314; 250 dry mountains … 400 humid coasts)" /></label>
        <label>{t('advanced.htxM')}<input value={htx} onChange={(e) => setHtx(e.target.value)} /></label>
        <label>{t('advanced.hrxM')}<input value={hrx} onChange={(e) => setHrx(e.target.value)} /></label>
      </div>
      <button className="primary" style={{ width: '100%' }} disabled={!tx || !rx || busy} onClick={go}>
        {busy ? t('advanced.running') : t('advanced.run')}
      </button>
      {err && <div className="warning-box" role="status">{err}</div>}
      {res && (
        <table className="result-table">
          <tbody>
            <tr><td>{t('advanced.pathLoss')}</td><td><b>{res.path_loss_db} dB</b> · {t('advanced.engineExact')}</td></tr>
            <tr><td>{t('advanced.freeSpace')}</td><td>{res.free_space_db} dB</td></tr>
            <tr><td>{t('advanced.refAtten')}</td><td>{res.reference_attenuation_db} dB</td></tr>
            <tr><td>{t('advanced.variability')}</td><td>{res.variability_plus_ref_db} dB</td></tr>
            <tr><td>{t('advanced.roughness')}</td><td>{res.terrain_dh_m} m</td></tr>
          </tbody>
        </table>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ P.1812
function P1812Tab({ tx, rx }: { tx: LatLng | null; rx: LatLng | null }) {
  const { t } = useTranslation();
  const [freq, setFreq] = useState('900');
  const [timePct, setTimePct] = useState('50');
  const [locPct, setLocPct] = useState('50');
  const [worldcover, setWorldcover] = useState(false);
  const [htx, setHtx] = useState('30');
  const [hrx, setHrx] = useState('10');
  const { busy, err, res, run } = useRun<any>();
  const go = () => tx && rx && run(() => p1812Study({
    lat1: tx.lat, lon1: tx.lng, lat2: rx.lat, lon2: rx.lng,
    freq_mhz: +freq, time_pct: +timePct, location_pct: +locPct,
    h_tx_m: +htx, h_rx_m: +hrx,
    ...(worldcover ? { clutter_source: 'worldcover' } : {}),
  }));
  return (
    <div>
      <p className="hint">{t('advanced.p1812Hint')}</p>
      <NeedMarkers tx={tx} rx={rx} />
      <div className="field-grid">
        <label>{t('advanced.freqMhz')}<input value={freq} onChange={(e) => setFreq(e.target.value)} /></label>
        <label>{t('advanced.timePct')}<input value={timePct} onChange={(e) => setTimePct(e.target.value)} /></label>
        <label>{t('advanced.locPct')}<input value={locPct} onChange={(e) => setLocPct(e.target.value)} /></label>
        <label>{t('advanced.htxM')}<input value={htx} onChange={(e) => setHtx(e.target.value)} /></label>
        <label>{t('advanced.hrxM')}<input value={hrx} onChange={(e) => setHrx(e.target.value)} /></label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <input type="checkbox" checked={worldcover}
            onChange={(e) => setWorldcover(e.target.checked)} />
          {t('advanced.worldcover')}
        </label>
      </div>
      <button className="primary" style={{ width: '100%' }} disabled={!tx || !rx || busy} onClick={go}>
        {busy ? t('advanced.running') : t('advanced.run')}
      </button>
      {err && <div className="warning-box" role="status">{err}</div>}
      {res && (
        <table className="result-table">
          <tbody>
            <tr><td>{t('advanced.pathLoss')}</td><td><b>{res.path_loss_db} dB</b> · {t('advanced.engineItu')}</td></tr>
            <tr><td>{t('advanced.freeSpace')}</td><td>{res.free_space_db} dB</td></tr>
            <tr><td>{t('advanced.excessFs')}</td><td>{res.excess_over_fs_db} dB</td></tr>
            <tr><td>{t('advanced.worldcover')}</td><td>{res.clutter_applied ? '✓' : '—'}</td></tr>
          </tbody>
        </table>
      )}
    </div>
  );
}

// ------------------------------------------------------------------- P.452
function P452Tab({ tx, rx }: { tx: LatLng | null; rx: LatLng | null }) {
  const { t } = useTranslation();
  const [freq, setFreq] = useState('6000');
  const [timePct, setTimePct] = useState('0.01');
  const [gt, setGt] = useState('0');
  const [gr, setGr] = useState('0');
  const [htx, setHtx] = useState('30');
  const [hrx, setHrx] = useState('30');
  const [worldcover, setWorldcover] = useState(false);
  const { busy, err, res, run } = useRun<any>();
  const go = () => tx && rx && run(() => p452Study({
    lat1: tx.lat, lon1: tx.lng, lat2: rx.lat, lon2: rx.lng,
    freq_mhz: +freq, time_pct: +timePct, gt_dbi: +gt, gr_dbi: +gr,
    h_tx_m: +htx, h_rx_m: +hrx,
    ...(worldcover ? { clutter_source: 'worldcover' } : {}),
  }));
  return (
    <div>
      <p className="hint">{t('advanced.p452Hint')}</p>
      <NeedMarkers tx={tx} rx={rx} />
      <div className="field-grid">
        <label>{t('advanced.freqMhz')}<input value={freq} onChange={(e) => setFreq(e.target.value)} /></label>
        <label>{t('advanced.timePct')}<input value={timePct}
          title="Small values (0.01 %) capture the rare ducting enhancements that set the interference worst case"
          onChange={(e) => setTimePct(e.target.value)} /></label>
        <label>{t('advanced.gtDbi')}<input value={gt} onChange={(e) => setGt(e.target.value)} /></label>
        <label>{t('advanced.grDbi')}<input value={gr} onChange={(e) => setGr(e.target.value)} /></label>
        <label>{t('advanced.htxM')}<input value={htx} onChange={(e) => setHtx(e.target.value)} /></label>
        <label>{t('advanced.hrxM')}<input value={hrx} onChange={(e) => setHrx(e.target.value)} /></label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <input type="checkbox" checked={worldcover}
            onChange={(e) => setWorldcover(e.target.checked)} />
          {t('advanced.worldcover')}
        </label>
      </div>
      <button className="primary" style={{ width: '100%' }} disabled={!tx || !rx || busy} onClick={go}>
        {busy ? t('advanced.running') : t('advanced.run')}
      </button>
      {err && <div className="warning-box" role="status">{err}</div>}
      {res && (
        <table className="result-table">
          <tbody>
            <tr><td>{t('advanced.interfLoss')}</td><td><b>{res.path_loss_db} dB</b> · {t('advanced.engineP452')}</td></tr>
            <tr><td>{t('advanced.freeSpace')}</td><td>{res.free_space_db} dB</td></tr>
            <tr><td>{t('advanced.excessFs')}</td><td>{res.excess_over_fs_db} dB</td></tr>
            <tr><td>{t('advanced.timePct')}</td><td>{res.time_pct} %</td></tr>
            <tr><td>{t('advanced.worldcover')}</td><td>{res.clutter_applied ? '✓' : '—'}</td></tr>
          </tbody>
        </table>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ P.2001
function P2001Tab({ tx, rx }: { tx: LatLng | null; rx: LatLng | null }) {
  const { t } = useTranslation();
  const [freq, setFreq] = useState('600');
  const [timePct, setTimePct] = useState('50');
  const [htx, setHtx] = useState('30');
  const [hrx, setHrx] = useState('30');
  const [gt, setGt] = useState('0');
  const [gr, setGr] = useState('0');
  const { busy, err, res, run } = useRun<any>();
  const go = () => tx && rx && run(() => p2001Study({
    lat1: tx.lat, lon1: tx.lng, lat2: rx.lat, lon2: rx.lng,
    freq_mhz: +freq, time_pct: +timePct,
    h_tx_m: +htx, h_rx_m: +hrx, gt_dbi: +gt, gr_dbi: +gr,
  }));
  return (
    <div>
      <p className="hint">{t('advanced.p2001Hint')}</p>
      <NeedMarkers tx={tx} rx={rx} />
      <div className="field-grid">
        <label>{t('advanced.freqMhz')}<input value={freq} onChange={(e) => setFreq(e.target.value)} /></label>
        <label>{t('advanced.timePct')}<input value={timePct}
          title="Full 0-100 % range in one model: 0.01 % = rare enhancements (ducting), 99.99 % = deep-fade planning"
          onChange={(e) => setTimePct(e.target.value)} /></label>
        <label>{t('advanced.htxM')}<input value={htx} onChange={(e) => setHtx(e.target.value)} /></label>
        <label>{t('advanced.hrxM')}<input value={hrx} onChange={(e) => setHrx(e.target.value)} /></label>
        <label>{t('advanced.gtDbi')}<input value={gt} onChange={(e) => setGt(e.target.value)} /></label>
        <label>{t('advanced.grDbi')}<input value={gr} onChange={(e) => setGr(e.target.value)} /></label>
      </div>
      <button className="primary" style={{ width: '100%' }} disabled={!tx || !rx || busy} onClick={go}>
        {busy ? t('advanced.running') : t('advanced.run')}
      </button>
      {err && <div className="warning-box" role="status">{err}</div>}
      {res && (
        <table className="result-table">
          <tbody>
            <tr><td>{t('advanced.pathLoss')}</td><td><b>{res.path_loss_db} dB</b> · {t('advanced.engineP2001')}</td></tr>
            <tr><td>{t('advanced.freeSpace')}</td><td>{res.free_space_db} dB</td></tr>
            <tr><td>{t('advanced.excessFs')}</td><td>{res.excess_over_fs_db} dB</td></tr>
            <tr><td>{t('advanced.timePct')}</td><td>{res.time_pct} %</td></tr>
          </tbody>
        </table>
      )}
    </div>
  );
}

// ------------------------------------------------------------- availability
const RAIN_ZONES = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K', 'L', 'M', 'N', 'P', 'Q'];

function AvailTab({ tx, rx }: { tx: LatLng | null; rx: LatLng | null }) {
  const { t } = useTranslation();
  const [zone, setZone] = useState('K');
  const [dn1, setDn1] = useState('-300');
  const [freq, setFreq] = useState('');       // '' = the preset's frequency
  const [margin, setMargin] = useState('');   // '' = real link-budget margin
  const [htx, setHtx] = useState('30');
  const [hrx, setHrx] = useState('30');
  const { busy, err, res, run } = useRun<any>();
  const go = () => tx && rx && run(() => availabilityStudy({
    lat1: tx.lat, lon1: tx.lng, lat2: rx.lat, lon2: rx.lng,
    technology: 'ptp18000', rain_zone: zone, dn1: +dn1,
    h_tx_m: +htx, h_rx_m: +hrx,
    ...(freq.trim() !== '' ? { freq_mhz: +freq } : {}),
    ...(margin.trim() !== '' ? { fade_margin_db: +margin } : {}),
  }));
  return (
    <div>
      <p className="hint">{t('advanced.availHint')}</p>
      <NeedMarkers tx={tx} rx={rx} />
      <div className="field-grid">
        <label>{t('advanced.rainZone')}
          <select value={zone} onChange={(e) => setZone(e.target.value)}>
            {RAIN_ZONES.map((z) => <option key={z} value={z}>{z}</option>)}
          </select>
        </label>
        <label>{t('advanced.dn1')}<input value={dn1} onChange={(e) => setDn1(e.target.value)} /></label>
        <label>{t('advanced.freqOverride')}<input value={freq} placeholder="18000"
          onChange={(e) => setFreq(e.target.value)} /></label>
        <label>{t('advanced.marginOverride')}<input value={margin} placeholder={t('advanced.auto')}
          title="Empty = the hop's real link-budget margin computed over the terrain"
          onChange={(e) => setMargin(e.target.value)} /></label>
        <label>{t('advanced.htxM')}<input value={htx} onChange={(e) => setHtx(e.target.value)} /></label>
        <label>{t('advanced.hrxM')}<input value={hrx} onChange={(e) => setHrx(e.target.value)} /></label>
      </div>
      <button className="primary" style={{ width: '100%' }} disabled={!tx || !rx || busy} onClick={go}>
        {busy ? t('advanced.running') : t('advanced.run')}
      </button>
      {err && <div className="warning-box" role="status">{err}</div>}
      {res && (
        <table className="result-table">
          <tbody>
            <tr><td>{t('advanced.availability')}</td><td><b>{res.availability_pct} %</b> — {res.nines}</td></tr>
            <tr><td>{t('advanced.downtime')}</td><td>{res.downtime_minutes_per_year} min/{t('advanced.year')}</td></tr>
            <tr><td>{t('advanced.outMultipath')}</td><td>{res.multipath_outage_pct} %</td></tr>
            <tr><td>{t('advanced.outRain')}</td><td>{res.rain_outage_pct} % ({t('advanced.rainZone')} {res.rain_zone}, A₀.₀₁ {res.rain_a001_db} dB)</td></tr>
            <tr><td>{t('advanced.marginUsed')}</td><td>{res.fade_margin_db} dB</td></tr>
          </tbody>
        </table>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ Erlang
function ErlangTab() {
  const { t } = useTranslation();
  const [traffic, setTraffic] = useState('10');
  const [channels, setChannels] = useState('12');
  const [gos, setGos] = useState('0.02');
  const [kind, setKind] = useState('b');
  const { busy, err, res, run } = useRun<any>();
  const go = () => run(() => erlangStudy({
    traffic_erlangs: +traffic, kind,
    ...(channels.trim() !== '' ? { channels: +channels } : {}),
    ...(gos.trim() !== '' ? { gos: +gos } : {}),
  }));
  return (
    <div>
      <p className="hint">{t('advanced.erlangHint')}</p>
      <div className="field-grid">
        <label>{t('advanced.traffic')}<input value={traffic} onChange={(e) => setTraffic(e.target.value)} /></label>
        <label>{t('advanced.channels')}<input value={channels} placeholder="—"
          onChange={(e) => setChannels(e.target.value)} /></label>
        <label>{t('advanced.gosTarget')}<input value={gos} placeholder="—"
          onChange={(e) => setGos(e.target.value)} /></label>
        <label>{t('advanced.erlangKind')}
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="b">Erlang B ({t('advanced.blocked')})</option>
            <option value="c">Erlang C ({t('advanced.queued')})</option>
          </select>
        </label>
      </div>
      <button className="primary" style={{ width: '100%' }} disabled={busy} onClick={go}>
        {busy ? t('advanced.running') : t('advanced.run')}
      </button>
      {err && <div className="warning-box" role="status">{err}</div>}
      {res && (
        <table className="result-table">
          <tbody>
            {res.blocking_probability !== undefined && (
              <tr><td>{kind === 'b' ? t('advanced.blocking') : t('advanced.waitProb')} ({res.channels} {t('advanced.channelsLc')})</td>
                <td><b>{(res.blocking_probability * 100).toFixed(2)} %</b></td></tr>
            )}
            {res.channels_for_gos !== undefined && (
              <tr><td>{t('advanced.channelsNeeded', { gos: (res.gos * 100).toFixed(1) })}</td>
                <td><b>{res.channels_for_gos}</b></td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ------------------------------------------------------------- calibration
function CalibTab({ tx, technology, calibration, onCalibration }: {
  tx: LatLng | null; technology: string | null;
  calibration: object | null; onCalibration: (c: object | null) => void;
}) {
  const { t } = useTranslation();
  const [raw, setRaw] = useState('');
  const { busy, err, res, run } = useRun<any>();
  // "lat, lon, rssi" per line — commas, semicolons or whitespace.
  const points = raw.split('\n').map((l) => l.trim()).filter(Boolean)
    .map((l) => l.split(/[,;\s]+/).map(Number))
    .filter((c) => c.length >= 3 && c.every(Number.isFinite)
                   && c[2] <= -10 && c[2] >= -150)
    .map(([lat, lon, rssi]) => ({ lat, lon, rssi_dbm: rssi }));
  const go = () => tx && run(() => calibrateDriveTest({
    tx_lat: tx.lat, tx_lon: tx.lng, technology: technology || 'custom',
    points,
  }));
  return (
    <div>
      <p className="hint">{t('advanced.calibHint')}</p>
      {!tx && <p className="hint">{t('advanced.needTx')}</p>}
      <label>
        {t('advanced.calibPoints')}
        <textarea rows={7} value={raw} placeholder={'47.05, 15.42, -87\n47.06, 15.43, -92'}
          onChange={(e) => setRaw(e.target.value)}
          style={{ width: '100%', font: '12px var(--mono)', marginTop: 4 }} />
      </label>
      <p className="hint">{t('advanced.calibParsed', { count: points.length })}</p>
      <button className="primary" style={{ width: '100%' }}
        disabled={!tx || points.length < 2 || busy} onClick={go}>
        {busy ? t('advanced.running') : t('advanced.calibFit')}
      </button>
      {err && <div className="warning-box" role="status">{err}</div>}
      {res && (
        <>
          <table className="result-table">
            <tbody>
              <tr><td>{t('advanced.calibRmseBefore')}</td><td>{res.fit.rms_error_before_db} dB</td></tr>
              <tr><td>{t('advanced.calibOffset')}</td>
                <td>{res.fit.offset_db > 0 ? '+' : ''}{res.fit.offset_db} dB → {res.fit.rms_error_offset_db} dB RMS</td></tr>
              <tr><td>{t('advanced.calibSlope')}</td>
                <td>{res.fit.slope_intercept_db} + {res.fit.slope_per_decade_db}/dec → {res.fit.rms_error_offset_slope_db} dB RMS</td></tr>
              <tr><td>{t('advanced.calibResidual')}</td><td>{res.fit.residual_std_db} dB</td></tr>
              <tr><td>{t('advanced.calibRecommended')}</td><td><b>{res.fit.recommended}</b></td></tr>
            </tbody>
          </table>
          <button className="primary" style={{ width: '100%', marginTop: 8 }}
            onClick={() => onCalibration(res.calibration)}>
            {t('advanced.calibApply')}
          </button>
        </>
      )}
      {calibration && (
        <div className="stat-line" style={{ marginTop: 8 }}>
          <span className="k">{t('advanced.calibActive')}</span>
          <span className="v">
            ✓ <button style={{ marginLeft: 8, padding: '1px 8px' }}
              onClick={() => onCalibration(null)}>{t('advanced.calibClear')}</button>
          </span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- copilot
function CopilotTab(
  { tx, rx, technology }: { tx: LatLng | null; rx: LatLng | null; technology: string | null },
) {
  const { t } = useTranslation();
  const { busy, err, res, run } = useRun<any>();
  const go = () => tx && rx && run(() => copilotAnalyzeLink({
    tx_lat: tx.lat, tx_lon: tx.lng, rx_lat: rx.lat, rx_lon: rx.lng,
    technology: technology || 'custom',
  }));
  const badge = (s: string) => s === 'critical' ? '🔴' : s === 'warning' ? '🟡' : '🟢';
  return (
    <div>
      <p className="hint">{t('advanced.copilotHint')}</p>
      <NeedMarkers tx={tx} rx={rx} />
      <button className="primary" style={{ width: '100%' }} disabled={!tx || !rx || busy} onClick={go}>
        {busy ? t('advanced.running') : t('advanced.analyze')}
      </button>
      {err && <div className="warning-box" role="status">{err}</div>}
      {res && (
        <div>
          <p style={{ whiteSpace: 'pre-line', marginTop: 10 }}>{res.summary}</p>
          <ul className="findings">
            {res.findings.map((f: any, i: number) => (
              <li key={i}><b>{badge(f.severity)} {f.issue}</b> — {f.action}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
