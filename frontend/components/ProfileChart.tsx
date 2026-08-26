'use client';

/**
 * TX→RX elevation profile (Recharts) with data-provenance color coding:
 * blue area = terrain sourced from SRTM, orange area = terrain sourced from
 * the DXF patch (blend samples count toward their dominant source).
 *
 * The plotted terrain is the *curved* profile (k=4/3 earth bulge applied),
 * matching what the RF line-of-sight / Fresnel math actually evaluates, so
 * the straight LOS line on the chart is geometrically honest.
 */
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Area, ComposedChart, Legend, Line, ReferenceDot, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts';
import type { ProfilePoint, ProfileResponse } from '@/lib/types';

const SRTM_COLOR = '#2a78d6';   // blue  = SRTM base
const DXF_COLOR = '#eb6834';    // orange = DXF patch
const SEAM_COLOR = '#12b3a6';   // teal  = fused seam (blend)
const FRESNEL_COLOR = '#38bdf8';

interface ChartRow {
  km: number;
  srtm: number | null;
  dxf: number | null;
  seam: number | null;          // terrain elevation at blended (seam) samples
  los: number;
  fresnel: number;              // 1st Fresnel lower edge (60%-clearance ref)
  fresnelZone: [number, number]; // [lower, upper] envelope for the shaded band
  source: string;
  rxPower?: number;
}

/** Cap the rendered point count so high-sample profiles (up to 2,048) never
 *  jank the SVG chart.  Buckets keep their highest-terrain sample, so peaks
 *  (which decide the RF verdict) are never smoothed away. */
const MAX_CHART_POINTS = 512;

export function downsample(points: ProfilePoint[]): ProfilePoint[] {
  if (points.length <= MAX_CHART_POINTS) return points;
  const bucket = Math.ceil(points.length / MAX_CHART_POINTS);
  const out: ProfilePoint[] = [points[0]];
  for (let i = 1; i < points.length - 1; i += bucket) {
    let best = points[i];
    for (let j = i; j < Math.min(i + bucket, points.length - 1); j++) {
      if (points[j].elev_curved > best.elev_curved) best = points[j];
    }
    out.push(best);
  }
  out.push(points[points.length - 1]);
  return out;
}

/** Split terrain into srtm/dxf series; duplicate boundary samples into both
 *  series so the two areas meet without a visual gap. */
function toRows(allPoints: ProfilePoint[]): ChartRow[] {
  const points = downsample(allPoints);
  const isDxf = (p: ProfilePoint) => p.dxf_weight >= 0.5;
  return points.map((p, i) => {
    const mine = isDxf(p);
    const prev = i > 0 ? isDxf(points[i - 1]) : mine;
    const next = i < points.length - 1 ? isDxf(points[i + 1]) : mine;
    const boundary = mine !== prev || mine !== next;
    // The first Fresnel radius is the gap between LOS and its lower edge; the
    // upper edge mirrors it, giving the full ellipse envelope around the LOS.
    const radius = p.los - p.fresnel_lower;
    return {
      km: p.d / 1000,
      srtm: !mine || boundary ? p.elev_curved : null,
      dxf: mine || boundary ? p.elev_curved : null,
      // Seam markers highlight where SRTM and DXF are blended (0<w<1).
      seam: p.source === 'blend' ? p.elev_curved : null,
      los: p.los,
      fresnel: p.fresnel_lower,
      fresnelZone: [p.fresnel_lower, p.los + radius],
      source: p.source,
      rxPower: p.rx_power_dbm,
    };
  });
}

function ProfileTooltip({ active, payload, label }: {
  active?: boolean;
  payload?: { payload: ChartRow }[];
  label?: number;
}) {
  const { t } = useTranslation();
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  const elev = row.dxf ?? row.srtm;
  return (
    <div style={{
      background: 'var(--surface-1)', border: '1px solid var(--hairline)',
      borderRadius: 8, padding: '8px 10px', fontSize: 12,
      boxShadow: '0 4px 14px rgba(0,0,0,0.12)',
    }}>
      <div style={{ fontWeight: 650, marginBottom: 4 }}>{Number(label).toFixed(2)} km</div>
      <div>{t('chart.terrain')}: <b>{elev?.toFixed(1)} m</b>{' '}
        <span className={`badge ${row.source === 'srtm' ? 'srtm' : 'dxf'}`}>
          {row.source.toUpperCase()}
        </span>
      </div>
      <div style={{ color: 'var(--ink-secondary)' }}>{t('chart.losShort')}: {row.los.toFixed(1)} m</div>
      <div style={{ color: 'var(--ink-secondary)' }}>{t('chart.f1Lower')}: {row.fresnel.toFixed(1)} m</div>
      {row.rxPower !== undefined && (
        <div style={{ color: 'var(--ink-secondary)' }}>{t('chart.rxPower')}: <b>{row.rxPower.toFixed(1)} dBm</b></div>
      )}
    </div>
  );
}

export default function ProfileChart({ profile }: { profile: ProfileResponse }) {
  const { t } = useTranslation();
  const rows = useMemo(() => toRows(profile.points), [profile]);
  const hasDxf = rows.some((r) => r.dxf !== null);

  return (
    <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', gap: 14, alignItems: 'baseline', padding: '0 4px' }}>
        <span style={{ fontWeight: 650, fontSize: 13 }}>
          Elevation profile — {(profile.distance_m / 1000).toFixed(2)} km
          @ {profile.rf.freq_mhz} MHz (k = 4/3 applied)
        </span>
        <span style={{ fontSize: 12, color: profile.rf.line_of_sight_clear ? 'var(--status-good)' : 'var(--status-critical)', fontWeight: 650 }}>
          {profile.rf.line_of_sight_clear ? '✓ Line of sight clear' : '✕ Path obstructed'}
        </span>
        <span style={{ fontSize: 12, color: 'var(--ink-secondary)' }}>
          Knife-edge loss: {profile.rf.knife_edge_loss_db.toFixed(1)} dB ·
          F1 clearance: {(profile.rf.fresnel_clearance_ratio * 100).toFixed(0)}%
        </span>
      </div>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={rows} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
          <XAxis
            dataKey="km" type="number" domain={['dataMin', 'dataMax']}
            tickFormatter={(v: number) => v.toFixed(1)}
            tick={{ fontSize: 11, fill: 'var(--ink-muted)' }}
            stroke="var(--baseline)"
            label={{ value: 'km', position: 'insideBottomRight', offset: -2, fontSize: 11, fill: 'var(--ink-muted)' }}
          />
          <YAxis
            domain={['auto', 'auto']} width={52}
            tick={{ fontSize: 11, fill: 'var(--ink-muted)' }}
            stroke="var(--baseline)"
            label={{ value: 'm', position: 'insideTopLeft', offset: 4, fontSize: 11, fill: 'var(--ink-muted)' }}
          />
          <Tooltip content={<ProfileTooltip />} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {/* Terrain, colored by provenance. connectNulls stays OFF so each
              area only spans its own provenance segments. */}
          <Area
            dataKey="srtm" name={t('chart.terrainSrtm')} stroke={SRTM_COLOR}
            fill={SRTM_COLOR} fillOpacity={0.35} strokeWidth={2}
            dot={false} activeDot={false} isAnimationActive={false}
          />
          {hasDxf && (
            <Area
              dataKey="dxf" name={t('chart.terrainDxf')} stroke={DXF_COLOR}
              fill={DXF_COLOR} fillOpacity={0.4} strokeWidth={2}
              dot={false} activeDot={false} isAnimationActive={false}
            />
          )}
          {/* Full 1st Fresnel zone as a shaded ellipse envelope (lower↔upper
              edge) around the sight line — terrain rising into this band
              degrades the link even with clear line of sight. */}
          <Area
            dataKey="fresnelZone" name={t('chart.fresnelZone')} stroke={FRESNEL_COLOR}
            fill={FRESNEL_COLOR} fillOpacity={0.14} strokeOpacity={0.5}
            strokeWidth={1} dot={false} activeDot={false} isAnimationActive={false}
          />
          {/* 60%-clearance reference (lower edge), then the TX-RX sight line. */}
          <Line
            dataKey="fresnel" name={t('chart.fresnelLower')} stroke="var(--ink-muted)"
            strokeDasharray="2 4" strokeWidth={1.5} dot={false} isAnimationActive={false}
          />
          <Line
            dataKey="los" name={t('chart.los')} stroke="var(--ink-primary)"
            strokeDasharray="6 4" strokeWidth={1.5} dot={false} isAnimationActive={false}
          />
          {/* Seam samples where SRTM and DXF are fused (teal dots). */}
          <Line
            dataKey="seam" name={t('chart.fusedSeam')} stroke={SEAM_COLOR} strokeWidth={0}
            dot={{ r: 2.5, fill: SEAM_COLOR, strokeWidth: 0 }}
            activeDot={false} isAnimationActive={false} legendType="circle"
          />
          {/* Mark the controlling obstruction (where a repeater/mast-raise
              would act) whenever the path is not comfortably clear. */}
          {profile.rf.worst_obstruction_v > -0.78 && (() => {
            const p = profile.points[profile.rf.worst_obstruction_index];
            return p ? (
              <ReferenceDot x={p.d / 1000} y={p.elev_curved} r={5}
                fill="var(--status-critical)" stroke="#fff" strokeWidth={1.5}
                label={{ value: t('chart.worstObstruction'), position: 'top', fontSize: 10,
                         fill: 'var(--status-critical)' }} />
            ) : null;
          })()}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
