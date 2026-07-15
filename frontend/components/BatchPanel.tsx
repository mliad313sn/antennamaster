'use client';

/**
 * Batch receiver qualification — the fixed-wireless/WISP workflow: paste a
 * list of subscriber/CPE locations (name,lat,lon per line) and qualify them
 * all against the current TX in one call.  Renders a served/margin table
 * and a CSV download.  Replaces the old "geocode → move RX → read → repeat"
 * grind that a 50-address survey otherwise required.
 */
import { useMemo, useState } from 'react';
import { batchReceivers, batchReceiversCsv } from '@/lib/api';
import type { BatchResponse, LatLng } from '@/lib/types';
import Help from '@/components/Help';

export interface BatchPanelProps {
  tx: LatLng | null;
  technology: string | null;
  dxfId: string | null;
  foliageDepth: number;
  rainRate: number;
  clutterPct: number;
  surfaceOn: boolean;
  onFocusReceiver?: (lat: number, lon: number) => void;
}

interface Parsed { name?: string; lat: number; lon: number; }

function parseReceivers(text: string): { rows: Parsed[]; errors: number } {
  const rows: Parsed[] = [];
  let errors = 0;
  for (const raw of text.split('\n')) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    // Accept "name,lat,lon" or "lat,lon" (comma / whitespace / semicolon).
    const parts = line.split(/[,;\t]+|\s{2,}/).map((s) => s.trim()).filter(Boolean);
    let name: string | undefined;
    let nums = parts;
    if (parts.length >= 3) { name = parts[0]; nums = parts.slice(1); }
    const lat = parseFloat(nums[0]); const lon = parseFloat(nums[1]);
    if (Number.isFinite(lat) && Number.isFinite(lon)
        && Math.abs(lat) <= 90 && Math.abs(lon) <= 180) {
      rows.push({ name, lat, lon });
    } else { errors += 1; }
  }
  return { rows, errors };
}

export default function BatchPanel(props: BatchPanelProps) {
  const [text, setText] = useState('');
  const [result, setResult] = useState<BatchResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { rows, errors } = useMemo(() => parseReceivers(text), [text]);

  function reqBody() {
    return {
      lat: props.tx!.lat, lon: props.tx!.lng,
      technology: props.technology!, receivers: rows,
      dxfId: props.dxfId,
      foliageDepthM: props.foliageDepth || undefined,
      rainRateMmH: props.rainRate || undefined,
      clutterPct: props.clutterPct || undefined,
      surface: props.surfaceOn || undefined,
    };
  }

  async function run() {
    if (!props.tx || !props.technology || rows.length === 0) return;
    setBusy(true); setError(null);
    try {
      setResult(await batchReceivers(reqBody()));
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  async function downloadCsv() {
    try {
      const blob = await batchReceiversCsv({
        lat: props.tx!.lat, lon: props.tx!.lng, technology: props.technology,
        receivers: rows,
        dxf_id: props.dxfId ?? undefined,
        foliage_depth_m: props.foliageDepth || undefined,
        rain_rate_mm_h: props.rainRate || undefined,
        clutter_pct: props.clutterPct || undefined,
        surface: props.surfaceOn || undefined,
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = 'batch-receivers.csv'; a.click();
      URL.revokeObjectURL(url);
    } catch (e) { setError((e as Error).message); }
  }

  if (!props.technology) {
    return (
      <div className="panel">
        <h3>Batch receivers<Help term="batch" /></h3>
        <p className="hint">Select a technology in the Radio study panel to
          qualify a list of receiver locations against the TX.</p>
      </div>
    );
  }

  return (
    <div className="panel">
      <h3>Batch receivers<Help term="batch" /></h3>
      <p className="hint">
        One row per site: <code>name,lat,lon</code> (name optional). Qualifies
        every location against the current TX — served/margin, LOS and Fresnel.
      </p>
      <textarea
        aria-label="Receiver list (name,lat,lon per line)"
        rows={5} value={text} placeholder={'Farm A,47.05,15.42\n47.06,15.44'}
        onChange={(e) => setText(e.target.value)}
        style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} />
      <div className="stat-line">
        <span className="k">{rows.length} valid{errors ? `, ${errors} skipped` : ''}</span>
        <span className="v">{rows.length > 200 ? '⚠ max 200' : ''}</span>
      </div>
      <button className="primary" style={{ width: '100%' }}
        disabled={!props.tx || busy || rows.length === 0 || rows.length > 200}
        onClick={run}>
        {busy ? 'Qualifying…' : props.tx
          ? `Qualify ${rows.length} receiver${rows.length === 1 ? '' : 's'}`
          : 'Place TX first'}
      </button>

      {result && (
        <>
          <div className="stat-line" style={{ marginTop: 8 }}>
            <span className="k">Served</span>
            <span className="v">
              {result.summary.served}/{result.summary.total}
              {' '}({(result.summary.served_fraction * 100).toFixed(0)}%)
            </span>
          </div>
          <div style={{ maxHeight: 220, overflowY: 'auto', marginTop: 4 }}>
            <table className="batch-table">
              <thead>
                <tr><th>Site</th><th>km</th><th>Margin</th><th>LOS</th></tr>
              </thead>
              <tbody>
                {result.receivers.map((r, i) => (
                  <tr key={i}
                    onClick={() => props.onFocusReceiver?.(r.lat, r.lon)}
                    style={{ cursor: props.onFocusReceiver ? 'pointer' : 'default' }}>
                    <td>{r.name}</td>
                    <td>{(r.distance_m / 1000).toFixed(1)}</td>
                    <td style={{ color: r.served
                      ? 'var(--status-good)' : 'var(--status-critical)' }}>
                      {r.margin_db.toFixed(1)} dB
                    </td>
                    <td>{r.los_clear ? '✓' : '✕'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button style={{ width: '100%', marginTop: 6 }} onClick={downloadCsv}>
            ⤓ Download CSV
          </button>
        </>
      )}
      {error && <div className="error-box">{error}</div>}
    </div>
  );
}
