'use client';

/**
 * Command Center — the Enterprise / Industrial IT-Manager dashboard:
 * project portfolio across sites, deployment CAPEX/OPEX estimates, plan
 * management and the OT/IT compliance (audit) log.
 */
import Link from 'next/link';
import { useEffect, useState, useId } from 'react';
import { useTranslation } from 'react-i18next';
import DashNav from '@/components/DashNav';
import {
  deleteProject, duplicateProject, fetchAudit, fetchCosts, fetchMe,
  listProjects, setTier, shareProject, uploadLogo,
  type CostEstimate, type Project, type User,
} from '@/lib/saas';

export default function Dashboard() {
  const { t } = useTranslation();
  const _uid = useId();
  // undefined = still loading, null = signed out, User = signed in.
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [projects, setProjects] = useState<Project[]>([]);
  const [audit, setAudit] = useState<{ action: string; detail: string;
    email: string | null; ts: number }[]>([]);
  const [costTech, setCostTech] = useState('private_nr_n77');
  const [costSites, setCostSites] = useState(4);
  const [costs, setCosts] = useState<CostEstimate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [shareUrl, setShareUrl] = useState<string | null>(null);

  useEffect(() => {
    fetchMe().then((u) => {
      setUser(u);
      if (u) {
        listProjects().then(setProjects).catch(() => {});
        if (u.role === 'manager') fetchAudit().then(setAudit).catch(() => {});
      }
    });
  }, []);
  useEffect(() => {
    fetchCosts(costTech, costSites).then(setCosts).catch(() => {});
  }, [costTech, costSites]);

  if (user === undefined) {
    return (
      <div className="dash-shell">
        <DashNav active="dashboard" />
        <p className="hint" style={{ padding: 24 }}>{t('dashboard.loading')}</p>
      </div>
    );
  }
  if (user === null) {
    return (
      <div className="dash-shell">
        <DashNav active="dashboard" />
        <p className="hint" style={{ padding: 24 }}>
          Sign in from the <Link href="/">planner</Link> to see your Command Center.
        </p>
      </div>
    );
  }

  return (
    <div className="dash-shell">
      <DashNav active="dashboard" />
      <main id="main" className="dash-main">
        <h1>{t('dashboard.title')}</h1>
        <p className="hint">{t('dashboard.subtitle', { org: user.org_name || user.email, tier: user.tier, count: projects.length })}</p>

        <div className="dash-grid">
          {/* -------------------------------------------------- projects */}
          <section className="panel">
            <h3>{t('dashboard.projects')}</h3>
            {projects.length === 0 && (
              <p className="hint">{t('dashboard.noProjects')}{' '}
                <Link href="/">{t('dashboard.plannerLink')}</Link>{' '}
                {t('dashboard.noProjectsTail')}</p>
            )}
            {projects.map((p) => (
              <div key={p.id} className="stat-line" style={{ alignItems: 'center' }}>
                <span className="k">
                  <b>{p.name}</b>
                  <span style={{ color: 'var(--ink-muted)', marginLeft: 6 }}>
                    {new Date(p.updated_at * 1000).toLocaleDateString()}
                  </span>
                </span>
                <span className="v" style={{ display: 'flex', gap: 4 }}>
                  <Link href={`/?project=${p.id}`}><button>{t('dashboard.open')}</button></Link>
                  <button onClick={async () => {
                    try {
                      await duplicateProject(p.id);
                      setProjects(await listProjects());
                    } catch (e) { setShareUrl(`Error: ${(e as Error).message}`); }
                  }}>{t('dashboard.duplicate')}</button>
                  <button onClick={async () => {
                    try {
                      const t = await shareProject(p.id);
                      // A real app link the recipient can open (no auth): the
                      // planner reads ?shared=<token> via the public endpoint.
                      setShareUrl(`${location.origin}/?shared=${t}`);
                    } catch (e) { setShareUrl(`Error: ${(e as Error).message}`); }
                  }}>{t('dashboard.share')}</button>
                  <button onClick={async () => {
                    try {
                      await deleteProject(p.id);
                      setProjects(await listProjects());
                    } catch (e) { setShareUrl(`Error: ${(e as Error).message}`); }
                  }} aria-label={`Delete ${p.name}`}>🗑</button>
                </span>
              </div>
            ))}
            {shareUrl && (
              <p className="hint" style={{ wordBreak: 'break-all' }}>
                Share link (read-only): {shareUrl}
              </p>
            )}
          </section>

          {/* ------------------------------------------------ CAPEX/OPEX */}
          <section className="panel">
            <h3>{t('dashboard.budget')}</h3>
            <div className="row">
              <div>
                <label htmlFor={`${_uid}-0`}>{t('dashboard.technology')}</label>
                <select id={`${_uid}-0`} value={costTech} onChange={(e) => setCostTech(e.target.value)}>
                  <option value="private_lte_b48">Private LTE (CBRS)</option>
                  <option value="private_nr_n77">Private 5G n77</option>
                  <option value="wifi5800">Wi-Fi PtMP</option>
                  <option value="ptp18000">Microwave PtP</option>
                  <option value="tetra400">TETRA</option>
                  <option value="gsm900">Macro GSM/LTE</option>
                  <option value="lora868">LoRaWAN</option>
                </select>
              </div>
              <div>
                <label htmlFor={`${_uid}-1`}>{t('dashboard.sites')}</label>
                <input id={`${_uid}-1`} type="number" min={1} max={500} value={costSites}
                  onChange={(e) => {
                    const v = parseInt(e.target.value, 10);
                    if (Number.isFinite(v) && v >= 1) setCostSites(v);
                  }} />
              </div>
            </div>
            {costs && (
              <>
                <div className="kpi-row">
                  <div className="kpi"><div className="kpi-v">${(costs.capex_total_usd / 1000).toFixed(0)}k</div><div className="kpi-k">{t('dashboard.capexTotal')}</div></div>
                  <div className="kpi"><div className="kpi-v">${(costs.opex_total_year_usd / 1000).toFixed(1)}k</div><div className="kpi-k">{t('dashboard.opexYear')}</div></div>
                  <div className="kpi"><div className="kpi-v">${(costs.tco_5y_usd / 1000).toFixed(0)}k</div><div className="kpi-k">5-year TCO</div></div>
                </div>
                {costs.bom_per_site.map((i) => (
                  <div key={i.item} className="stat-line">
                    <span className="k">{i.item} ×{i.qty}</span>
                    <span className="v">${i.line_usd.toLocaleString()}</span>
                  </div>
                ))}
                <a className="download-link" style={{ marginTop: 8 }}
                  href={`/api/saas/bom.csv?technology=${encodeURIComponent(costTech)}&sites=${costSites}`}
                  download>
                  ⤓ Bill of materials (CSV, {costSites} site{costSites === 1 ? '' : 's'})
                </a>
              </>
            )}
          </section>

          {/* ------------------------------------------------- plan & brand */}
          <section className="panel">
            <h3>{t('dashboard.planBranding')}</h3>
            <div className="stat-line"><span className="k">{t('dashboard.currentPlan')}</span><span className="v">{user.tier}</span></div>
            <div className="row">
              {['basic', 'pro', 'enterprise'].map((t) => (
                <button key={t} className={user.tier === t ? 'primary' : ''}
                  onClick={async () => setUser(await setTier(t))}>
                  {t}
                </button>
              ))}
            </div>
            <label htmlFor={`${_uid}-2`} style={{ marginTop: 8 }}>{t('dashboard.logoLabel')}</label>
            <input id={`${_uid}-2`} type="file" accept="image/png,image/jpeg"
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (!f) return;
                try { await uploadLogo(f); setError(null); setUser(await fetchMe()); }
                catch (err) { setError((err as Error).message); }
              }} />
            {user.has_logo && <p className="hint">{t('dashboard.logoOnFile')}</p>}
            {error && <div className="error-box" role="alert">{error}</div>}
          </section>

          {/* --------------------------------------------------- audit log */}
          {user.role === 'manager' && (
            <section className="panel" style={{ gridColumn: '1 / -1' }}>
              <h3>{t('dashboard.auditLog')}</h3>
              <div style={{ maxHeight: 220, overflowY: 'auto' }}>
                {audit.map((a, i) => (
                  <div key={i} className="stat-line">
                    <span className="k">{new Date(a.ts * 1000).toLocaleString()} — {a.email ?? t('dashboard.anonymous')}</span>
                    <span className="v">{a.action}{a.detail ? ` · ${a.detail}` : ''}</span>
                  </div>
                ))}
                {audit.length === 0 && <p className="hint">{t('dashboard.noActivity')}</p>}
              </div>
            </section>
          )}
        </div>
      </main>
    </div>
  );
}

