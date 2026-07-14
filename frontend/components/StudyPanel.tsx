'use client';

/**
 * Radio study panel: pick a technology preset (2G GSM ... 5G NR mmWave,
 * PMR, broadcast, Wi-Fi, IoT, microwave PtP), optionally override the
 * propagation model / environment, and run an area coverage simulation from
 * the TX site.  Shows the coverage legend and the point-to-point link budget
 * of the current profile.
 */
import { useEffect, useMemo, useState } from 'react';
import { fetchModels, fetchTechnologies, simulateCoverage } from '@/lib/api';
import type {
  CoverageResponse, LatLng, ModelInfo, StudyResult, Technology,
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
  study: StudyResult | null;
  coverage: CoverageResponse | null;
  onCoverage: (c: CoverageResponse | null) => void;
}

export default function StudyPanel(props: StudyPanelProps) {
  const [techs, setTechs] = useState<Technology[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [radiusKm, setRadiusKm] = useState(8);
  const [sector, setSector] = useState(false);
  const [azimuth, setAzimuth] = useState(0);
  const [beamwidth, setBeamwidth] = useState(65);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchTechnologies().then(setTechs).catch(() => setTechs([]));
    fetchModels().then(setModels).catch(() => setModels([]));
  }, []);

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
        antennaAzimuthDeg: sector ? azimuth : null,
        antennaBeamwidthDeg: beamwidth,
        hBsM: props.txHeight || undefined,
      });
      props.onCoverage(resp);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel">
      <h3>Radio study</h3>
      <label>Technology</label>
      <select
        value={props.technology ?? ''}
        onChange={(e) => {
          props.onTechnologyChange(e.target.value || null);
          props.onModelChange(null);
          props.onEnvironmentChange(null);
        }}
      >
        <option value="">— none (terrain only) —</option>
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
              <label>Propagation model</label>
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
              <label>Environment</label>
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
            <span className="k">Preset</span>
            <span className="v">
              {selectedTech.freq_mhz.toLocaleString()} MHz ·
              TX {selectedTech.tx_power_dbm} dBm · sens {selectedTech.rx_sensitivity_dbm} dBm
            </span>
          </div>

          {/* ---------------- link budget of the current profile ---------- */}
          {props.study && (
            <div style={{ borderTop: '1px solid var(--hairline)', marginTop: 8, paddingTop: 8 }}>
              <div className="stat-line"><span className="k">Path loss ({props.study.technology.model})</span><span className="v">{props.study.path_loss_db.toFixed(1)} dB</span></div>
              <div className="stat-line"><span className="k">Diffraction (Deygout)</span><span className="v">{props.study.diffraction_loss_db.toFixed(1)} dB</span></div>
              <div className="stat-line"><span className="k">RX power</span><span className="v">{props.study.rx_power_dbm.toFixed(1)} dBm</span></div>
              <div className="stat-line">
                <span className="k">Margin</span>
                <span className="v" style={{ color: props.study.served ? 'var(--status-good)' : 'var(--status-critical)' }}>
                  {props.study.margin_db.toFixed(1)} dB {props.study.served ? '(served)' : '(no service)'}
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
                <label>Radius (km)</label>
                <input type="number" min={1} max={150} value={radiusKm}
                  onChange={(e) => setRadiusKm(parseFloat(e.target.value) || 1)} />
              </div>
              <div>
                <label style={{ marginBottom: 6 }}>Antenna</label>
                <select value={sector ? 'sector' : 'omni'}
                  onChange={(e) => setSector(e.target.value === 'sector')}>
                  <option value="omni">Omni</option>
                  <option value="sector">Sector</option>
                </select>
              </div>
            </div>
            {sector && (
              <div className="row">
                <div>
                  <label>Azimuth (°)</label>
                  <input type="number" min={0} max={359} value={azimuth}
                    onChange={(e) => setAzimuth(parseFloat(e.target.value) || 0)} />
                </div>
                <div>
                  <label>Beamwidth (°)</label>
                  <input type="number" min={10} max={360} value={beamwidth}
                    onChange={(e) => setBeamwidth(parseFloat(e.target.value) || 65)} />
                </div>
              </div>
            )}
            <button className="primary" style={{ width: '100%' }}
              disabled={!props.tx || busy} onClick={runCoverage}>
              {busy ? 'Simulating…' : props.tx ? 'Simulate coverage from TX' : 'Place TX first'}
            </button>
            {props.coverage && (
              <>
                <div className="stat-line" style={{ marginTop: 8 }}>
                  <span className="k">Served area</span>
                  <span className="v">{(props.coverage.stats.served_area_fraction * 100).toFixed(0)}%</span>
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
                  Clear coverage layer
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
