'use client';

/**
 * Pitch Interface — the pre-sales architect's screen: run scenario A vs B
 * coverage comparisons with live progress, compute a quick ROI, and export
 * the branded executive PDF in one click.
 */
import Link from 'next/link';
import { useEffect, useState, useId } from 'react';
import { useTranslation } from 'react-i18next';
import {
  awaitJob, downloadReportPdf, fetchCosts, fetchMe, startAsyncCoverage,
  type CostEstimate,
} from '@/lib/saas';
import { fetchTechnologies } from '@/lib/api';
import { roi } from '@/lib/roi';
import { useAuthedAsset } from '@/lib/authedAsset';
import type { Technology } from '@/lib/types';
import DashNav from '@/components/DashNav';
import SignalLegend from '@/components/SignalLegend';

interface Scenario {
  label: string;
  technology: string;
  radiusKm: number;
  downtilt: number;
  progress: number;
  running: boolean;
  result: { png_url: string; served: number | null; peak: number } | null;
}

const empty = (label: string): Scenario => ({
  label, technology: 'private_lte_b48', radiusKm: 6, downtilt: 0,
  progress: 0, running: false, result: null,
});

export default function Pitch() {
  const { t } = useTranslation();
  const _uid = useId();
  const [lat, setLat] = useState('47.05');
  const [lon, setLon] = useState('15.45');
  const [a, setA] = useState<Scenario>(empty(t('pitch.optionA')));
  const [b, setB] = useState<Scenario>({ ...empty(t('pitch.optionB')), technology: 'wifi5800' });
  const [techs, setTechs] = useState<Technology[]>([]);
  const [costsA, setCostsA] = useState<CostEstimate | null>(null);
  const [costsB, setCostsB] = useState<CostEstimate | null>(null);
  const [sites, setSites] = useState(3);
  const [revenuePerMonth, setRevenuePerMonth] = useState(8000);
  const [error, setError] = useState<string | null>(null);
  // What this account may do, straight from the gate that enforces it, so a
  // capability it lacks is named rather than offered and then refused.
  const [canPdf, setCanPdf] = useState(true);
  // Owner-scoped rasters: an <img> cannot carry the bearer token, so a
  // signed-in user's own heatmap came back 404 and painted nothing. Hooks at
  // component level because `card` below is a render helper called twice.
  const aSrc = useAuthedAsset(a.result?.png_url);
  const bSrc = useAuthedAsset(b.result?.png_url);

  useEffect(() => {
    fetchMe().then((u) => setCanPdf(u?.features?.pdf_export !== false))
      .catch(() => {});
  }, []);
  useEffect(() => {
    fetchTechnologies().then((list) => {
      setTechs(list);
      // Default to something this account can actually run. Option A shipped
      // pointing at Private LTE B48, which needs the Enterprise plan - so a
      // new basic account's very first action on the screen built for showing
      // a customer failed with "Upgrade to continue", while the dropdown was
      // full of presets it could have run.
      const usable = (k: string) => list.find((t) => t.key === k)?.available !== false;
      const firstUsable = list.find((t) => t.available !== false)?.key;
      if (firstUsable) {
        setA((s) => (usable(s.technology) ? s : { ...s, technology: firstUsable, result: null }));
        setB((s) => (usable(s.technology) ? s : { ...s, technology: firstUsable, result: null }));
      }
    }).catch(() => {});
  }, []);
  useEffect(() => {
    fetchCosts(a.technology, sites).then(setCostsA).catch(() => {});
    fetchCosts(b.technology, sites).then(setCostsB).catch(() => {});
  }, [a.technology, b.technology, sites]);

  async function run(which: 'a' | 'b') {
    const sc = which === 'a' ? a : b;
    const set = which === 'a' ? setA : setB;
    set({ ...sc, running: true, progress: 0, result: null });
    setError(null);
    try {
      const jobId = await startAsyncCoverage({
        lat: parseFloat(lat), lon: parseFloat(lon),
        technology: sc.technology, radius_km: sc.radiusKm,
        downtilt_deg: sc.downtilt, n_radials: 180, n_steps: 100,
      });
      const job = await awaitJob(jobId, (p) => set((s) => ({ ...s, progress: p })));
      if (job.status === 'failed') throw new Error(job.error ?? 'job failed');
      const r = job.result as { png_url: string;
        stats: { served_area_fraction: number | null; max_rx_power_dbm: number } };
      set((s) => ({ ...s, running: false, progress: 1,
        result: { png_url: r.png_url, served: r.stats.served_area_fraction,
                  peak: r.stats.max_rx_power_dbm } }));
    } catch (e) {
      setError((e as Error).message);
      set((s) => ({ ...s, running: false }));
    }
  }

  async function exportPdf(sc: Scenario) {
    try {
      // The headline figures are NOT sent. The report endpoint reads them
      // from the stored study behind `coverage_id`, because a signed document
      // whose served-area number came from the client is a fabrication
      // vector — so those two fields were removed from its schema, which
      // rejects unknown keys. This screen kept sending them, so every
      // Executive PDF export answered 422 and the button did nothing but put
      // a validation error in the box. Measured: 0 of 4 attempts produced a
      // file, on both a basic and an enterprise account.
      await downloadReportPdf({
        title: `${sc.label} — ${sc.technology} @ ${lat}, ${lon}`,
        technology: sc.technology, sites,
        coverage_id: sc.result?.png_url.split('/').pop()?.replace('.png', ''),
      });
    } catch (e) { setError((e as Error).message); }
  }

  const card = (sc: Scenario, set: (s: Scenario) => void, which: 'a' | 'b',
                costs: CostEstimate | null, src: string | null) => (
    <section className="panel" style={{ flex: 1, minWidth: 0 }}>
      <h3>{sc.label}</h3>
      <label htmlFor={`${_uid}-0`}>{t('pitch.technology')}</label>
      <select id={`${_uid}-0`} value={sc.technology}
        onChange={(e) => set({ ...sc, technology: e.target.value, result: null })}>
        {/* A preset the account cannot run is named as such rather than
            looking identical to the rest and failing on submit. Still
            selectable: seeing the boundary is the point, and the error that
            follows a deliberate choice is informative rather than baffling. */}
        {techs.map((t) => (
          <option key={t.key} value={t.key}>
            {t.label}{t.available === false && t.requires_plan
              ? ` — ${t.requires_plan} plan` : ''}
          </option>
        ))}
      </select>
      <div className="row" style={{ marginTop: 6 }}>
        <div>
          <label htmlFor={`${_uid}-1`}>{t('pitch.radius')}</label>
          <input id={`${_uid}-1`} type="number" min={1} max={50} value={sc.radiusKm}
            onChange={(e) => set({ ...sc, radiusKm: parseFloat(e.target.value) || 6 })} />
        </div>
        <div>
          <label htmlFor={`${_uid}-2`}>{t('pitch.downtilt')}</label>
          <input id={`${_uid}-2`} type="number" min={0} max={15} value={sc.downtilt}
            onChange={(e) => set({ ...sc, downtilt: parseFloat(e.target.value) || 0 })} />
        </div>
      </div>
      <button className="primary" style={{ width: '100%' }} disabled={sc.running}
        onClick={() => run(which)}>
        {sc.running ? t('pitch.simulating', { pct: (sc.progress * 100).toFixed(0) }) : t('pitch.runCoverage')}
      </button>
      {sc.running && (
        <div className="progress"><div className="progress-fill"
          style={{ width: `${sc.progress * 100}%` }} /></div>
      )}
      {sc.result && src && (
        <>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={src} alt={t('pitch.heatmapAlt', { label: sc.label })}
            style={{ width: '100%', marginTop: 8, borderRadius: 8,
                     border: '1px solid var(--hairline)',
                     background: 'var(--page)' }} />
          <div className="kpi-row">
            <div className="kpi"><div className="kpi-v">{sc.result.served !== null ? `${(sc.result.served * 100).toFixed(0)}%` : '—'}</div><div className="kpi-k">{t('pitch.servedArea')}</div></div>
            <div className="kpi"><div className="kpi-v">{sc.result.peak.toFixed(0)}</div><div className="kpi-k">{t('pitch.peakDbm')}</div></div>
            <div className="kpi"><div className="kpi-v">{roi(revenuePerMonth, costs, sc.result.served).payback}</div><div className="kpi-k">payback</div></div>
            <div className="kpi"><div className="kpi-v">{roi(revenuePerMonth, costs, sc.result.served).y5}</div><div className="kpi-k">5-yr net</div></div>
          </div>
          {sc.result.served !== null && (
            <p className="hint" style={{ marginTop: 6 }}>
              {t('pitch.roiAssumption', {
                pct: (sc.result.served * 100).toFixed(0),
                earned: Math.round(revenuePerMonth * sc.result.served).toLocaleString(),
              })}
            </p>
          )}
          <SignalLegend peakDbm={sc.result.peak} />
          <button style={{ width: '100%' }} onClick={() => exportPdf(sc)}
            title={canPdf ? undefined : t('pitch.pdfNeedsPro')}>
            ⤓ Executive PDF{canPdf ? '' : ' — pro plan'}
          </button>
        </>
      )}
      {costs && (
        <p className="hint">{t('pitch.costs', {
          capex: (costs.capex_total_usd / 1000).toFixed(0),
          opex: (costs.opex_total_year_usd / 1000).toFixed(1),
          tco: (costs.tco_5y_usd / 1000).toFixed(0),
        })}</p>
      )}
    </section>
  );

  return (
    <div className="dash-shell">
      <DashNav active="pitch" />
      <main id="main" className="dash-main">
        <h1>{t('pitch.title')}</h1>
        <p className="hint">{t('pitch.intro')}{' '}
          <Link href="/">{t('pitch.plannerLink')}</Link></p>
        <div className="row" style={{ maxWidth: 560 }}>
          <div><label htmlFor={`${_uid}-3`}>{t('pitch.siteLat')}</label>
            <input id={`${_uid}-3`} value={lat} onChange={(e) => setLat(e.target.value)} /></div>
          <div><label htmlFor={`${_uid}-4`}>{t('pitch.siteLon')}</label>
            <input id={`${_uid}-4`} value={lon} onChange={(e) => setLon(e.target.value)} /></div>
          <div><label htmlFor={`${_uid}-5`}>{t('pitch.sites')}</label>
            <input id={`${_uid}-5`} type="number" min={1} max={100} value={sites}
              onChange={(e) => {
                const v = parseInt(e.target.value, 10);
                if (Number.isFinite(v) && v >= 1) setSites(v);
              }} /></div>
          <div><label htmlFor={`${_uid}-6`}>{t('pitch.revenue')}</label>
            <input id={`${_uid}-6`} type="number" value={revenuePerMonth}
              onChange={(e) => {
                const v = parseFloat(e.target.value);
                if (Number.isFinite(v)) setRevenuePerMonth(v);
              }} /></div>
        </div>
        <div style={{ display: 'flex', gap: 14, marginTop: 10, flexWrap: 'wrap' }}>
          {card(a, setA, 'a', costsA, aSrc)}
          {card(b, setB, 'b', costsB, bSrc)}
        </div>
        {error && <div className="error-box" role="alert">{error}</div>}
      </main>
    </div>
  );
}
