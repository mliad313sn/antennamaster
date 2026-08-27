'use client';

/**
 * The site inventory of a cluster study: add, edit, import, export.
 *
 * Two gaps this closes. A site could be added and removed but never
 * *corrected* — a mistyped coordinate or a wrong azimuth meant deleting the
 * row and re-clicking the map, which on a twelve-site estate is how people
 * give up on a tool. And the per-site radio overrides that make a real estate
 * expressible (an 800 MHz macro layer, a 3.5 GHz capacity layer, a 400 MHz
 * PMR overlay in one study) existed only in the API: the UI cloned one preset
 * across every transmitter, so the composite described a network that does
 * not exist.
 *
 * Every override is blank by default and blank means inherit — from the
 * study-level value, then the preset. That is deliberate: a field pre-filled
 * with the inherited number looks like a decision someone made, and a planner
 * reading the study later cannot tell an override from a default.
 */
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { exportSitesCsv, parseSitesCsv } from '@/lib/api';
import { SITE_RADIO_FIELDS, type SiteEntry, type SiteRadioField } from '@/lib/types';

/** Unit shown next to each override, so nobody types metres into a dB field. */
const UNITS: Record<SiteRadioField, string> = {
  freq_mhz: 'MHz', tx_power_dbm: 'dBm', tx_gain_dbi: 'dBi', rx_gain_dbi: 'dBi',
  losses_db: 'dB', rx_sensitivity_dbm: 'dBm', h_bs_m: 'm', h_ut_m: 'm',
  antenna_beamwidth_deg: '°',
};

function numOrNull(v: string): number | null {
  const t = v.trim();
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

export default function SiteList({ sites, onChange, disabled }: {
  sites: SiteEntry[];
  onChange: (next: SiteEntry[]) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const [openIdx, setOpenIdx] = useState<number | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<{ line: number; reason: string }[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  function patch(i: number, fields: Partial<SiteEntry>) {
    onChange(sites.map((s, j) => (j === i ? { ...s, ...fields } : s)));
  }

  async function importCsv(file: File) {
    setMsg(null); setSkipped([]);
    try {
      const parsed = await parseSitesCsv(file);
      onChange([...sites, ...parsed.sites].slice(0, 24));
      setMsg(t('sites.imported', { count: parsed.count }));
      // Never drop rejected rows in silence: a planner who imports 40 sites
      // and studies 38 must be told which two, and why.
      setSkipped(parsed.skipped ?? []);
    } catch (e) {
      setMsg((e as Error).message);
    }
  }

  async function download() {
    setMsg(null);
    try {
      const csv = await exportSitesCsv(sites);
      const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
      const a = document.createElement('a');
      a.href = url; a.download = 'sites.csv'; a.click();
      URL.revokeObjectURL(url);
    } catch (e) { setMsg((e as Error).message); }
  }

  return (
    <div className="site-list">
      <div style={{ display: 'flex', gap: 4, marginTop: 4 }}>
        <button style={{ flex: 1 }} disabled={disabled}
          onClick={() => fileRef.current?.click()}>
          {t('sites.import')}
        </button>
        <button style={{ flex: 1 }} disabled={disabled || !sites.length}
          onClick={download}>
          {t('sites.export')}
        </button>
        <input ref={fileRef} type="file" accept=".csv,text/csv"
          style={{ display: 'none' }} aria-hidden="true" tabIndex={-1}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) importCsv(f);
            e.target.value = '';           // let the same file be re-picked
          }} />
      </div>

      {msg && <p className="hint" role="status">{msg}</p>}
      {skipped.length > 0 && (
        <ul className="warning-box" style={{ margin: '4px 0', paddingLeft: 18 }}>
          {skipped.slice(0, 8).map((s) => (
            <li key={s.line}>{t('sites.skippedRow', { line: s.line })}: {s.reason}</li>
          ))}
          {skipped.length > 8 && <li>+{skipped.length - 8}</li>}
        </ul>
      )}

      {sites.map((s, i) => {
        const overrides = SITE_RADIO_FIELDS.filter((f) => s[f] != null).length;
        const open = openIdx === i;
        return (
          <div key={i} className={`site-row${open ? ' open' : ''}`}>
            <div className="stat-line">
              <span className="k">
                <button className="link-btn" aria-expanded={open}
                  onClick={() => setOpenIdx(open ? null : i)}>
                  {open ? '▾' : '▸'} {s.name}
                </button>
                {overrides > 0 && (
                  <span className="badge" title={t('sites.overridesHint')}>
                    {t('sites.overrides', { count: overrides })}
                  </span>
                )}
              </span>
              <span className="v">
                {s.lat.toFixed(4)}, {s.lon.toFixed(4)}
                <button style={{ marginLeft: 6, padding: '0 6px' }}
                  aria-label={t('sites.remove', { name: s.name })}
                  onClick={() => {
                    onChange(sites.filter((_, j) => j !== i));
                    setOpenIdx(null);
                  }}>−</button>
              </span>
            </div>

            {open && (
              <div className="site-editor">
                <div className="row">
                  <div>
                    <label htmlFor={`site-${i}-name`}>{t('sites.name')}</label>
                    <input id={`site-${i}-name`} value={s.name}
                      onChange={(e) => patch(i, { name: e.target.value })} />
                  </div>
                  <div>
                    <label htmlFor={`site-${i}-lat`}>{t('sites.lat')}</label>
                    <input id={`site-${i}-lat`} type="number" step="0.0001"
                      value={s.lat}
                      onChange={(e) => patch(i, { lat: Number(e.target.value) })} />
                  </div>
                  <div>
                    <label htmlFor={`site-${i}-lon`}>{t('sites.lon')}</label>
                    <input id={`site-${i}-lon`} type="number" step="0.0001"
                      value={s.lon}
                      onChange={(e) => patch(i, { lon: Number(e.target.value) })} />
                  </div>
                </div>
                <div className="row">
                  <div>
                    <label htmlFor={`site-${i}-az`}>{t('sites.azimuth')}</label>
                    <input id={`site-${i}-az`} type="number" min={0} max={360}
                      placeholder={t('sites.omni')}
                      value={s.antenna_azimuth_deg ?? ''}
                      onChange={(e) => patch(i, {
                        antenna_azimuth_deg: numOrNull(e.target.value) })} />
                  </div>
                  <div>
                    <label htmlFor={`site-${i}-tilt`}>{t('sites.downtilt')}</label>
                    <input id={`site-${i}-tilt`} type="number" step="0.5"
                      value={s.downtilt_deg ?? 0}
                      onChange={(e) => patch(i, {
                        downtilt_deg: Number(e.target.value) || 0 })} />
                  </div>
                </div>

                <p className="hint" style={{ marginTop: 6 }}>
                  {t('sites.overrideHelp')}
                </p>
                <div className="site-overrides">
                  {SITE_RADIO_FIELDS.map((f) => (
                    <div key={f}>
                      <label htmlFor={`site-${i}-${f}`}>
                        {t(`sites.field.${f}`)} <span className="unit">{UNITS[f]}</span>
                      </label>
                      <input id={`site-${i}-${f}`} type="number"
                        placeholder={t('sites.inherit')}
                        value={s[f] ?? ''}
                        onChange={(e) => patch(i, { [f]: numOrNull(e.target.value) })} />
                    </div>
                  ))}
                </div>
                {overrides > 0 && (
                  <button style={{ marginTop: 6 }}
                    onClick={() => patch(i, Object.fromEntries(
                      SITE_RADIO_FIELDS.map((f) => [f, null])) as Partial<SiteEntry>)}>
                    {t('sites.clearOverrides', { count: overrides })}
                  </button>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
