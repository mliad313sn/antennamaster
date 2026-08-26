'use client';

/**
 * Simple Mode — the non-technical entry point.  Instead of dBi / MHz / model
 * choices, the user answers "what are you trying to connect?" and picks an
 * outcome.  The backend maps that to the right preset + study defaults
 * (see services/rf/scenarios.py), which we apply to the planner state; the
 * RF knobs stay hidden.
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { fetchScenarios, resolveScenario } from '@/lib/api';
import type { Scenario, ScenarioResolved } from '@/lib/types';

export interface SimpleModeProps {
  onApply: (s: ScenarioResolved) => void;
  onExpert: () => void;
}

export default function SimpleMode({ onApply, onExpert }: SimpleModeProps) {
  const { t } = useTranslation();
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [applied, setApplied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchScenarios().then(setScenarios).catch(() => setScenarios([]));
  }, []);

  async function choose(id: string) {
    setSelected(id);
    setApplied(false);
    setError(null);
  }

  async function apply() {
    if (!selected) return;
    try {
      const resolved = await resolveScenario(selected);
      onApply(resolved);
      setApplied(true);
    } catch (e) { setError((e as Error).message); }
  }

  const active = scenarios.find((s) => s.id === selected) ?? null;

  return (
    <div className="panel simple-panel" data-tour="simple">
      <h3>{t('simple.heading')}</h3>
      <p className="hint">{t('simple.sub')}</p>
      <div className="scenario-grid">
        {scenarios.map((s) => (
          <button
            key={s.id}
            type="button"
            className={`scenario-card ${selected === s.id ? 'sel' : ''}`}
            aria-pressed={selected === s.id}
            onClick={() => choose(s.id)}
          >
            <span className="scenario-icon" aria-hidden="true">{s.icon}</span>
            <span className="scenario-label">{t(s.label)}</span>
          </button>
        ))}
      </div>

      {active && (
        <div className="scenario-detail">
          <p className="hint">{t(active.blurb)}</p>
          <div className="stat-line">
            <span className="k">{t('simple.uses', { tech: active.technology_label })}</span>
          </div>
          <button className="primary" style={{ width: '100%' }} onClick={apply}>
            {t('simple.apply')}
          </button>
          {applied && (
            <p className="hint" style={{ color: 'var(--status-good)' }}>
              ✓ {t('simple.applied')}
            </p>
          )}
        </div>
      )}

      <button className="link-btn" onClick={onExpert} style={{ marginTop: 10 }}>
        {t('simple.advanced')} →
      </button>
      {error && <div className="error-box" role="alert">{error}</div>}
    </div>
  );
}
