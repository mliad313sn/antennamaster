'use client';

/**
 * Three-step modal: (1) upload a DXF, (2) pick the layers that carry terrain,
 * (3) georeference it with one of the three modes (known CRS / 2-3 control
 * points solving a Helmert transform / origin + bearing + unit scale).
 *
 * On success the parent receives the GeorefResponse (footprint, overlay,
 * validation) and renders it on the map.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { georeference, uploadDxf } from '@/lib/api';
import type {
  ControlPointPair, GeorefMode, GeorefResponse, LayerInfo, UploadResponse,
} from '@/lib/types';



export interface DxfWizardProps {
  onClose: () => void;
  onGeoreferenced: (r: GeorefResponse) => void;
}

export default function DxfWizard({ onClose, onGeoreferenced }: DxfWizardProps) {
  const { t } = useTranslation();
  const STEPS = [t('dxf.stepUpload'), t('dxf.stepLayers'), t('dxf.stepGeoref')];
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [upload, setUpload] = useState<UploadResponse | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const [mode, setMode] = useState<GeorefMode>('known_crs');
  const [crs, setCrs] = useState('EPSG:32633');
  const [unitScale, setUnitScale] = useState(1.0);
  const [originLat, setOriginLat] = useState('47.0');
  const [originLon, setOriginLon] = useState('15.0');
  const [bearing, setBearing] = useState('0');
  const [originX, setOriginX] = useState('0');
  const [originY, setOriginY] = useState('0');
  // Kept as raw strings so users can type '-', '.', or partial decimals
  // (southern/western coordinates were impossible with numeric state).
  type CpDraft = { dxf_x: string; dxf_y: string; lat: string; lon: string };
  const [cps, setCps] = useState<CpDraft[]>([
    { dxf_x: '0', dxf_y: '0', lat: '47', lon: '15' },
    { dxf_x: '1000', dxf_y: '0', lat: '47', lon: '15.013' },
  ]);

  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', esc);
    return () => window.removeEventListener('keydown', esc);
  }, [onClose]);

  // ------------------------------------------------------------- handlers
  const [hint, setHint] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  async function handleFile(file: File) {
    setBusy(true);
    setError(null);
    try {
      const resp = await uploadDxf(file);
      setUpload(resp);
      // Preselect layers that look like terrain (varying Z, has points).
      setSelected(new Set(
        resp.layers.filter((l) => l.looks_like_terrain).map((l) => l.name),
      ));
      // Frictionless onboarding: apply the backend's mode/unit guesses.
      const h = resp.georef_hints;
      if (h) {
        setMode(h.suggested_mode);
        if (h.suggested_unit_scale) setUnitScale(h.suggested_unit_scale);
        setHint(t('dxf.autoDetect', {
          mode: h.suggested_mode.replace('_', ' '),
          unit: h.suggested_unit === 'ft' ? 'feet' : 'meters',
          reason: h.reason,
        }));
      }
      setStep(1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function toggleLayer(name: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  }

  const selectedPointCount = useMemo(() => {
    if (!upload) return 0;
    return upload.layers
      .filter((l) => selected.has(l.name))
      .reduce((acc, l) => acc + l.point_count, 0);
  }, [upload, selected]);

  async function applyGeoref() {
    if (!upload) return;
    setBusy(true);
    setError(null);
    try {
      const base = { layers: Array.from(selected), unit_scale: unitScale };
      const req =
        mode === 'known_crs'
          ? { mode, ...base, crs, z_scale: unitScale }
          : mode === 'control_points'
            ? { mode, ...base, control_points: parsedCps(), z_scale: unitScale }
            : {
                mode, ...base,
                origin_lat: parseFloat(originLat), origin_lon: parseFloat(originLon),
                bearing_deg: parseFloat(bearing),
                origin_x: parseFloat(originX), origin_y: parseFloat(originY),
              };
      const resp = await georeference(upload.dxf_id, req);
      onGeoreferenced(resp);
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function setCp(i: number, key: keyof CpDraft, v: string) {
    setCps((prev) => prev.map((p, j) => (j === i ? { ...p, [key]: v } : p)));
  }

  const parsedCps = (): ControlPointPair[] => cps.map((p) => ({
    dxf_x: parseFloat(p.dxf_x), dxf_y: parseFloat(p.dxf_y),
    lat: parseFloat(p.lat), lon: parseFloat(p.lon),
  }));
  const cpsValid = cps.every((p) =>
    [p.dxf_x, p.dxf_y, p.lat, p.lon].every((v) => Number.isFinite(parseFloat(v))));

  const georefValid =
    selected.size > 0 &&
    (mode !== 'control_points' || (cps.length >= 2 && cps.length <= 3 && cpsValid));

  // --------------------------------------------------------------- render
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>{t('dxf.importTitle')}</h2>
          <button onClick={onClose} aria-label={t('dxf.close')}>✕</button>
        </div>
        <div className="modal-body">
          <div className="steps">
            {STEPS.map((s, i) => (
              <div key={s} className={`step ${i === step ? 'active' : i < step ? 'done' : ''}`}>
                {i + 1}. {s}
              </div>
            ))}
          </div>

          {step === 0 && (
            <div>
              <p className="hint">{t('dxf.uploadHint')}</p>
              <div
                className={`dropzone ${dragOver ? 'over' : ''}`}
                onClick={() => fileRef.current?.click()}
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragOver(false);
                  const f = e.dataTransfer.files?.[0];
                  if (f) handleFile(f);
                }}
                role="button" tabIndex={0} aria-label={t('dxf.uploadAria')}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileRef.current?.click(); } }}
              >
                <b>{t('dxf.dropHere')}</b><br />
                <span style={{ fontSize: 12 }}>{t('dxf.dropBrowse')}</span>
              </div>
              <input
                ref={fileRef} type="file" accept=".dxf" style={{ display: 'none' }}
                onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
              />
              {busy && <p className="hint">{t('dxf.parsing')}</p>}
            </div>
          )}

          {step === 1 && upload && (
            <div>
              <p className="hint">{t('dxf.layersHint', { points: selectedPointCount.toLocaleString() })}</p>
              {upload.layers.map((l: LayerInfo) => (
                <div key={l.name} className="layer-row" onClick={() => toggleLayer(l.name)}>
                  <input
                    type="checkbox" checked={selected.has(l.name)} readOnly
                    onClick={(e) => e.stopPropagation()}
                    onChange={() => toggleLayer(l.name)}
                  />
                  <span className="name">{l.name}</span>
                  <span className="meta">
                    {l.point_count.toLocaleString()} {t('dxf.pts')}
                    {l.z_min !== null && l.z_max !== null &&
                      ` · Z ${l.z_min.toFixed(1)}–${l.z_max.toFixed(1)}`}
                    {' · '}{l.entity_types.join(', ') || t('dxf.empty')}
                  </span>
                </div>
              ))}
            </div>
          )}

          {step === 2 && (
            <div>
              {hint && <div className="warning-box" style={{ marginBottom: 10 }}>💡 {hint}</div>}
              <div className="mode-tabs">
                <button className={mode === 'known_crs' ? 'active' : ''} onClick={() => setMode('known_crs')}>{t('dxf.modeKnownCrs')}</button>
                <button className={mode === 'control_points' ? 'active' : ''} onClick={() => setMode('control_points')}>{t('dxf.modeControlPoints')}</button>
                <button className={mode === 'origin_bearing' ? 'active' : ''} onClick={() => setMode('origin_bearing')}>{t('dxf.modeOrigin')}</button>
              </div>

              {mode === 'known_crs' && (
                <div>
                  <p className="hint">{t('dxf.knownCrsHint')}</p>
                  <label>{t('dxf.crsLabel')}</label>
                  <input value={crs} onChange={(e) => setCrs(e.target.value)} placeholder="EPSG:32633" />
                </div>
              )}

              {mode === 'control_points' && (
                <div>
                  <p className="hint">{t('dxf.cpHint')}</p>
                  {cps.map((cp, i) => (
                    <div key={i} className="cp-grid">
                      <div><label>{t('dxf.dxfX')}</label><input value={cp.dxf_x} onChange={(e) => setCp(i, 'dxf_x', e.target.value)} /></div>
                      <div><label>{t('dxf.dxfY')}</label><input value={cp.dxf_y} onChange={(e) => setCp(i, 'dxf_y', e.target.value)} /></div>
                      <div><label>{t('dxf.lat')}</label><input value={cp.lat} onChange={(e) => setCp(i, 'lat', e.target.value)} /></div>
                      <div><label>{t('dxf.lon')}</label><input value={cp.lon} onChange={(e) => setCp(i, 'lon', e.target.value)} /></div>
                      <button
                        disabled={cps.length <= 2}
                        onClick={() => setCps((prev) => prev.filter((_, j) => j !== i))}
                        title={t('dxf.removePoint')}
                      >−</button>
                    </div>
                  ))}
                  <button
                    disabled={cps.length >= 3}
                    onClick={() => setCps((prev) => [...prev, { dxf_x: '0', dxf_y: '0', lat: '47', lon: '15' }])}
                  >{t('dxf.addPoint')}</button>
                </div>
              )}

              {mode === 'origin_bearing' && (
                <div>
                  <p className="hint">{t('dxf.originHint')}</p>
                  <div className="row">
                    <div><label>{t('dxf.originLat')}</label><input value={originLat} onChange={(e) => setOriginLat(e.target.value)} /></div>
                    <div><label>{t('dxf.originLon')}</label><input value={originLon} onChange={(e) => setOriginLon(e.target.value)} /></div>
                  </div>
                  <div className="row">
                    <div><label>{t('dxf.dxfXOrigin')}</label><input value={originX} onChange={(e) => setOriginX(e.target.value)} /></div>
                    <div><label>{t('dxf.dxfYOrigin')}</label><input value={originY} onChange={(e) => setOriginY(e.target.value)} /></div>
                  </div>
                  <div className="row">
                    <div><label>{t('dxf.bearing')}</label><input value={bearing} onChange={(e) => setBearing(e.target.value)} /></div>
                  </div>
                </div>
              )}

              <div className="row" style={{ marginTop: 10 }}>
                <div>
                  <label>{t('dxf.drawingUnits')}</label>
                  <select value={unitScale} onChange={(e) => setUnitScale(parseFloat(e.target.value))}>
                    <option value={1}>{t('dxf.meters')}</option>
                    <option value={0.3048}>{t('dxf.feet')}</option>
                    <option value={0.9144}>{t('dxf.yards')}</option>
                    <option value={0.01}>{t('dxf.centimeters')}</option>
                  </select>
                </div>
              </div>
            </div>
          )}

          {error && <div className="error-box">{error}</div>}
        </div>

        <div className="modal-foot">
          <button onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0 || busy}>{t('dxf.back')}</button>
          {step === 1 && (
            <button className="primary" disabled={selected.size === 0} onClick={() => setStep(2)}>{t('dxf.nextGeoref')}</button>
          )}
          {step === 2 && (
            <button className="primary" disabled={!georefValid || busy} onClick={applyGeoref}>
              {busy ? t('dxf.georeferencing') : t('dxf.applyGeoref')}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
