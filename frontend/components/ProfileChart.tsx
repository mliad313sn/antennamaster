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
import {
  Area, ComposedChart, Legend, Line, ReferenceDot, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts';
import type { ProfilePoint, ProfileResponse } from '@/lib/types';

const SRTM_COLOR = '#2a78d6';
const DXF_COLOR = '#eb6834';

interface ChartRow {
  km: number;
  srtm: number | null;
  dxf: number | null;
  los: number;
  fresnel: number;
  source: string;
  rxPower?: number;
}

/** Split terrain into srtm/dxf series; duplicate boundary samples into both
 *  series so the two areas meet without a visual gap. */
function toRows(points: ProfilePoint[]): ChartRow[] {
  const isDxf = (p: ProfilePoint) => p.dxf_weight >= 0.5;
  return points.map((p, i) => {
    const mine = isDxf(p);
    const prev = i > 0 ? isDxf(points[i - 1]) : mine;
    const next = i < points.length - 1 ? isDxf(points[i + 1]) : mine;
    const boundary = mine !== prev || mine !== next;
    return {
      km: p.d / 1000,
      srtm: !mine || boundary ? p.elev_curved : null,
      dxf: mine || boundary ? p.elev_curved : null,
      los: p.los,
      fresnel: p.fresnel_lower,
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
      <div>Terrain: <b>{elev?.toFixed(1)} m</b>{' '}
        <span className={`badge ${row.source === 'srtm' ? 'srtm' : 'dxf'}`}>
          {row.source.toUpperCase()}
        </span>
      </div>
      <div style={{ color: 'var(--ink-secondary)' }}>LOS: {row.los.toFixed(1)} m</div>
      <div style={{ color: 'var(--ink-secondary)' }}>F1 lower: {row.fresnel.toFixed(1)} m</div>
      {row.rxPower !== undefined && (
        <div style={{ color: 'var(--ink-secondary)' }}>RX power: <b>{row.rxPower.toFixed(1)} dBm</b></div>
      )}
    </div>
  );
}

export default function ProfileChart({ profile }: { profile: ProfileResponse }) {
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
            dataKey="srtm" name="Terrain (SRTM)" stroke={SRTM_COLOR}
            fill={SRTM_COLOR} fillOpacity={0.35} strokeWidth={2}
            dot={false} activeDot={false} isAnimationActive={false}
          />
          {hasDxf && (
            <Area
              dataKey="dxf" name="Terrain (DXF)" stroke={DXF_COLOR}
              fill={DXF_COLOR} fillOpacity={0.4} strokeWidth={2}
              dot={false} activeDot={false} isAnimationActive={false}
            />
          )}
          {/* First Fresnel zone lower edge, then the TX-RX sight line. */}
          <Line
            dataKey="fresnel" name="1st Fresnel lower" stroke="var(--ink-muted)"
            strokeDasharray="2 4" strokeWidth={1.5} dot={false} isAnimationActive={false}
          />
          <Line
            dataKey="los" name="Line of sight" stroke="var(--ink-primary)"
            strokeDasharray="6 4" strokeWidth={1.5} dot={false} isAnimationActive={false}
          />
          {/* Mark the controlling obstruction (where a repeater/mast-raise
              would act) whenever the path is not comfortably clear. */}
          {profile.rf.worst_obstruction_v > -0.78 && (() => {
            const p = profile.points[profile.rf.worst_obstruction_index];
            return p ? (
              <ReferenceDot x={p.d / 1000} y={p.elev_curved} r={5}
                fill="var(--status-critical)" stroke="#fff" strokeWidth={1.5}
                label={{ value: 'worst obstruction', position: 'top', fontSize: 10,
                         fill: 'var(--status-critical)' }} />
            ) : null;
          })()}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
