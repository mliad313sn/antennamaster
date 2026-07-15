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
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  availabilityStudy, copilotAnalyzeLink, emfCompliance, emfReportPdf,
  itmStudy, p1812Study, twowayLink,
} from '@/lib/api';

type LatLng = { lat: number; lng: number };
type Tab = 'twoway' | 'emf' | 'itm' | 'p1812' | 'avail' | 'copilot';

export default function AdvancedStudies(
  { tx, rx, technology, onClose }:
  { tx: LatLng | null; rx: LatLng | null; technology: string | null; onClose: () => void },
) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>('twoway');
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', esc);
    return () => window.removeEventListener('keydown', esc);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" style={{ width: 820 }} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>{t('advanced.title')}</h2>
          <button onClick={onClose} aria-label={t('advanced.close')}>✕</button>
        </div>
        <div className="modal-body">
          <div className="mode-tabs">
            <button className={tab === 'twoway' ? 'active' : ''} onClick={() => setTab('twoway')}>{t('advanced.tabTwoway')}</button>
            <button className={tab === 'emf' ? 'active' : ''} onClick={() => setTab('emf')}>{t('advanced.tabEmf')}</button>
            <button className={tab === 'itm' ? 'active' : ''} onClick={() => setTab('itm')}>{t('advanced.tabItm')}</button>
            <button className={tab === 'p1812' ? 'active' : ''} onClick={() => setTab('p1812')}>{t('advanced.tabP1812')}</button>
            <button className={tab === 'avail' ? 'active' : ''} onClick={() => setTab('avail')}>{t('advanced.tabAvail')}</button>
            <button className={tab === 'copilot' ? 'active' : ''} onClick={() => setTab('copilot')}>{t('advanced.tabCopilot')}</button>
          </div>
          {tab === 'twoway' && <TwoWayTab tx={tx} rx={rx} />}
          {tab === 'emf' && <EmfTab />}
          {tab === 'itm' && <ItmTab tx={tx} rx={rx} />}
          {tab === 'p1812' && <P1812Tab tx={tx} rx={rx} />}
          {tab === 'avail' && <AvailTab tx={tx} rx={rx} />}
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
      {err && <div className="warning-box">{err}</div>}
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
  const [std, setStd] = useState('icnirp');
  const { busy, err, res, run } = useRun<any>();
  const [pdfBusy, setPdfBusy] = useState(false);
  const go = () => run(() => emfCompliance({
    freq_mhz: +freq, tx_power_dbm: +power, antenna_gain_dbi: +gain, standard: std,
  }));
  const downloadPdf = async () => {
    setPdfBusy(true);
    try {
      const blob = await emfReportPdf({
        site: { name: 'AntennaMaster site' },
        antennas: [{ label: 'Antenna 1', freq_mhz: +freq, tx_power_dbm: +power, antenna_gain_dbi: +gain }],
        standard: std,
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'emf-compliance.pdf';
      a.click();
      URL.revokeObjectURL(url);
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
      {err && <div className="warning-box">{err}</div>}
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
    </div>
  );
}

// -------------------------------------------------------------------- ITM
function ItmTab({ tx, rx }: { tx: LatLng | null; rx: LatLng | null }) {
  const { t } = useTranslation();
  const [freq, setFreq] = useState('900');
  const [rel, setRel] = useState('0.9');
  const { busy, err, res, run } = useRun<any>();
  const go = () => tx && rx && run(() => itmStudy({
    lat1: tx.lat, lon1: tx.lng, lat2: rx.lat, lon2: rx.lng,
    freq_mhz: +freq, reliability: +rel, confidence: 0.5,
  }));
  return (
    <div>
      <p className="hint">{t('advanced.itmHint')}</p>
      <NeedMarkers tx={tx} rx={rx} />
      <div className="field-grid">
        <label>{t('advanced.freqMhz')}<input value={freq} onChange={(e) => setFreq(e.target.value)} /></label>
        <label>{t('advanced.reliability')}<input value={rel} onChange={(e) => setRel(e.target.value)} /></label>
      </div>
      <button className="primary" style={{ width: '100%' }} disabled={!tx || !rx || busy} onClick={go}>
        {busy ? t('advanced.running') : t('advanced.run')}
      </button>
      {err && <div className="warning-box">{err}</div>}
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
  const { busy, err, res, run } = useRun<any>();
  const go = () => tx && rx && run(() => p1812Study({
    lat1: tx.lat, lon1: tx.lng, lat2: rx.lat, lon2: rx.lng,
    freq_mhz: +freq, time_pct: +timePct, location_pct: +locPct,
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
        <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <input type="checkbox" checked={worldcover}
            onChange={(e) => setWorldcover(e.target.checked)} />
          {t('advanced.worldcover')}
        </label>
      </div>
      <button className="primary" style={{ width: '100%' }} disabled={!tx || !rx || busy} onClick={go}>
        {busy ? t('advanced.running') : t('advanced.run')}
      </button>
      {err && <div className="warning-box">{err}</div>}
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

// ------------------------------------------------------------- availability
const RAIN_ZONES = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K', 'L', 'M', 'N', 'P', 'Q'];

function AvailTab({ tx, rx }: { tx: LatLng | null; rx: LatLng | null }) {
  const { t } = useTranslation();
  const [zone, setZone] = useState('K');
  const [dn1, setDn1] = useState('-300');
  const { busy, err, res, run } = useRun<any>();
  const go = () => tx && rx && run(() => availabilityStudy({
    lat1: tx.lat, lon1: tx.lng, lat2: rx.lat, lon2: rx.lng,
    technology: 'ptp18000', rain_zone: zone, dn1: +dn1,
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
      </div>
      <button className="primary" style={{ width: '100%' }} disabled={!tx || !rx || busy} onClick={go}>
        {busy ? t('advanced.running') : t('advanced.run')}
      </button>
      {err && <div className="warning-box">{err}</div>}
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
      {err && <div className="warning-box">{err}</div>}
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
