'use client';

/**
 * Pitch Interface — the pre-sales architect's screen: run scenario A vs B
 * coverage comparisons with live progress, compute a quick ROI, and export
 * the branded executive PDF in one click.
 */
import Link from 'next/link';
import { useEffect, useState } from 'react';
import {
  awaitJob, downloadReportPdf, fetchCosts, startAsyncCoverage,
  type CostEstimate,
} from '@/lib/saas';
import { fetchTechnologies } from '@/lib/api';
import type { Technology } from '@/lib/types';
import DashNav from '@/components/DashNav';

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
  const [lat, setLat] = useState('47.05');
  const [lon, setLon] = useState('15.45');
  const [a, setA] = useState<Scenario>(empty('Option A'));
  const [b, setB] = useState<Scenario>({ ...empty('Option B'), technology: 'wifi5800' });
  const [techs, setTechs] = useState<Technology[]>([]);
  const [costsA, setCostsA] = useState<CostEstimate | null>(null);
  const [costsB, setCostsB] = useState<CostEstimate | null>(null);
  const [sites, setSites] = useState(3);
  const [revenuePerMonth, setRevenuePerMonth] = useState(8000);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { fetchTechnologies().then(setTechs).catch(() => {}); }, []);
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

  function roi(costs: CostEstimate | null): { payback: string; y5: string } {
    if (!costs) return { payback: '—', y5: '—' };
    const monthly = revenuePerMonth - costs.opex_total_year_usd / 12;
    if (monthly <= 0) return { payback: 'never', y5: '—' };
    const months = costs.capex_total_usd / monthly;
    const y5 = revenuePerMonth * 60 - costs.tco_5y_usd;
    return { payback: `${months.toFixed(1)} mo`,
             y5: `${y5 >= 0 ? '+' : ''}$${(y5 / 1000).toFixed(0)}k` };
  }

  async function exportPdf(sc: Scenario) {
    try {
      await downloadReportPdf({
        title: `${sc.label} — ${sc.technology} @ ${lat}, ${lon}`,
        technology: sc.technology, sites,
        coverage_id: sc.result?.png_url.split('/').pop()?.replace('.png', ''),
        served_area_fraction: sc.result?.served ?? undefined,
        max_rx_power_dbm: sc.result?.peak,
      });
    } catch (e) { setError((e as Error).message); }
  }

  const card = (sc: Scenario, set: (s: Scenario) => void, which: 'a' | 'b',
                costs: CostEstimate | null) => (
    <section className="panel" style={{ flex: 1, minWidth: 0 }}>
      <h3>{sc.label}</h3>
      <label>Technology</label>
      <select value={sc.technology}
        onChange={(e) => set({ ...sc, technology: e.target.value, result: null })}>
        {techs.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
      </select>
      <div className="row" style={{ marginTop: 6 }}>
        <div>
          <label>Radius (km)</label>
          <input type="number" min={1} max={50} value={sc.radiusKm}
            onChange={(e) => set({ ...sc, radiusKm: parseFloat(e.target.value) || 6 })} />
        </div>
        <div>
          <label>Downtilt (°)</label>
          <input type="number" min={0} max={15} value={sc.downtilt}
            onChange={(e) => set({ ...sc, downtilt: parseFloat(e.target.value) || 0 })} />
        </div>
      </div>
      <button className="primary" style={{ width: '100%' }} disabled={sc.running}
        onClick={() => run(which)}>
        {sc.running ? `Simulating… ${(sc.progress * 100).toFixed(0)}%` : 'Run coverage'}
      </button>
      {sc.running && (
        <div className="progress"><div className="progress-fill"
          style={{ width: `${sc.progress * 100}%` }} /></div>
      )}
      {sc.result && (
        <>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={sc.result.png_url} alt={`${sc.label} coverage heatmap`}
            style={{ width: '100%', marginTop: 8, borderRadius: 8,
                     border: '1px solid var(--hairline)',
                     background: 'var(--page)' }} />
          <div className="kpi-row">
            <div className="kpi"><div className="kpi-v">{sc.result.served !== null ? `${(sc.result.served * 100).toFixed(0)}%` : '—'}</div><div className="kpi-k">served area</div></div>
            <div className="kpi"><div className="kpi-v">{sc.result.peak.toFixed(0)}</div><div className="kpi-k">peak dBm</div></div>
            <div className="kpi"><div className="kpi-v">{roi(costs).payback}</div><div className="kpi-k">payback</div></div>
            <div className="kpi"><div className="kpi-v">{roi(costs).y5}</div><div className="kpi-k">5-yr net</div></div>
          </div>
          <button style={{ width: '100%' }} onClick={() => exportPdf(sc)}>
            ⤓ Executive PDF
          </button>
        </>
      )}
      {costs && (
        <p className="hint">CAPEX ${(costs.capex_total_usd / 1000).toFixed(0)}k ·
          OPEX ${(costs.opex_total_year_usd / 1000).toFixed(1)}k/yr ·
          TCO₅ ${(costs.tco_5y_usd / 1000).toFixed(0)}k</p>
      )}
    </section>
  );

  return (
    <div className="dash-shell">
      <DashNav active="pitch" />
      <main className="dash-main">
        <h1>Pitch interface</h1>
        <p className="hint">Compare two deployment options side by side, with live
          simulation progress, budget and payback — then export the branded PDF.
          Deep-dive edits belong in the <Link href="/">planner</Link>.</p>
        <div className="row" style={{ maxWidth: 560 }}>
          <div><label>Site latitude</label>
            <input value={lat} onChange={(e) => setLat(e.target.value)} /></div>
          <div><label>Site longitude</label>
            <input value={lon} onChange={(e) => setLon(e.target.value)} /></div>
          <div><label>Sites</label>
            <input type="number" min={1} max={100} value={sites}
              onChange={(e) => setSites(parseInt(e.target.value, 10) || 1)} /></div>
          <div><label>Revenue $/mo (fleet)</label>
            <input type="number" value={revenuePerMonth}
              onChange={(e) => setRevenuePerMonth(parseFloat(e.target.value) || 0)} /></div>
        </div>
        <div style={{ display: 'flex', gap: 14, marginTop: 10, flexWrap: 'wrap' }}>
          {card(a, setA, 'a', costsA)}
          {card(b, setB, 'b', costsB)}
        </div>
        {error && <div className="error-box">{error}</div>}
      </main>
    </div>
  );
}
