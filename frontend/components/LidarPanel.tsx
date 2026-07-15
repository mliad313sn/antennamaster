'use client';

/**
 * LiDAR panel — ingest a drone .las/.laz survey into a Digital Surface Model
 * that overrides the statistical clutter with real 3D obstructions, then run a
 * profile whose diffraction is computed against the surveyed buildings/trees.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { lidarProfile, uploadLidar } from '@/lib/api';

type LatLng = { lat: number; lng: number };

export default function LidarPanel(
  { tx, rx, freqMhz }: { tx: LatLng | null; rx: LatLng | null; freqMhz: number },
) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [dsm, setDsm] = useState<any>(null);
  const [prof, setProf] = useState<any>(null);

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true); setErr(null); setProf(null);
    try { setDsm(await uploadLidar(file)); }
    catch (ex) { setErr(ex instanceof Error ? ex.message : String(ex)); }
    finally { setBusy(false); }
  }

  async function runProfile() {
    if (!dsm || !tx || !rx) return;
    setBusy(true); setErr(null);
    try {
      setProf(await lidarProfile(dsm.dsm_id, {
        lat1: tx.lat, lon1: tx.lng, lat2: rx.lat, lon2: rx.lng,
        h_tx_m: 5, h_rx_m: 1.5, freq_mhz: freqMhz || 2400,
      }));
    } catch (ex) { setErr(ex instanceof Error ? ex.message : String(ex)); }
    finally { setBusy(false); }
  }

  return (
    <div className="panel">
      <h3>{t('lidar.title')}</h3>
      <p className="hint">{t('lidar.hint')}</p>
      <label className="file-btn">
        {busy && !dsm ? t('lidar.parsing') : t('lidar.upload')}
        <input type="file" accept=".las,.laz" onChange={onFile} style={{ display: 'none' }} />
      </label>
      {err && <div className="warning-box">{err}</div>}
      {dsm && (
        <div style={{ marginTop: 8 }}>
          <table className="result-table">
            <tbody>
              <tr><td>{t('lidar.points')}</td><td>{dsm.n_points.toLocaleString()}</td></tr>
              <tr><td>{t('lidar.surface')}</td><td>{dsm.stats.surface_min_m}–{dsm.stats.surface_max_m} m</td></tr>
              {dsm.stats.max_object_height_m != null && (
                <tr><td>{t('lidar.objHeight')}</td><td>{dsm.stats.max_object_height_m} m</td></tr>
              )}
            </tbody>
          </table>
          <button style={{ width: '100%', marginTop: 8 }} disabled={!tx || !rx || busy} onClick={runProfile}>
            {t('lidar.runProfile')}
          </button>
          {!tx || !rx ? <p className="hint">{t('lidar.needMarkers')}</p> : null}
        </div>
      )}
      {prof && (
        <table className="result-table" style={{ marginTop: 8 }}>
          <tbody>
            <tr><td>{t('lidar.surfaceDiff')}</td><td>{prof.surface.diffraction_loss_db} dB</td></tr>
            <tr><td>{t('lidar.bareDiff')}</td><td>{prof.bare_terrain.diffraction_loss_db} dB</td></tr>
            <tr><td><b>{t('lidar.extraLoss')}</b></td><td><b>+{prof.extra_loss_from_surface_db} dB</b></td></tr>
            <tr><td>{t('lidar.maxObstruction')}</td><td>{prof.max_obstruction_m} m</td></tr>
          </tbody>
        </table>
      )}
    </div>
  );
}
