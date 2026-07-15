'use client';

/**
 * Signal-quality legend — maps received power (dBm) to a plain-language quality
 * grade a non-technical client understands. Used on the pre-sales pitch view so
 * a peak-dBm number reads as "Excellent / Good / Fair / Marginal", matching the
 * margin classes the coverage raster is coloured by.
 */
import { useTranslation } from 'react-i18next';

// dBm thresholds → grade (aligned with the coverage engine's 5 margin classes).
const BANDS = [
  { min: -65, color: '#0d366b', key: 'excellent' },
  { min: -75, color: '#184f95', key: 'veryGood' },
  { min: -85, color: '#256abf', key: 'good' },
  { min: -95, color: '#5598e7', key: 'fair' },
  { min: -110, color: '#9ec5f4', key: 'marginal' },
];

export function gradeForDbm(dbm: number): { key: string; color: string } {
  for (const b of BANDS) if (dbm >= b.min) return { key: b.key, color: b.color };
  return { key: 'none', color: '#64748b' };
}

export default function SignalLegend({ peakDbm }: { peakDbm?: number }) {
  const { t } = useTranslation();
  return (
    <div className="signal-legend">
      <div className="signal-legend-title">{t('legend.title')}</div>
      <div className="signal-legend-bands">
        {BANDS.map((b, i) => {
          const upper = i === 0 ? '' : `${BANDS[i - 1].min}`;
          const active = peakDbm != null && gradeForDbm(peakDbm).key === b.key;
          return (
            <div key={b.key} className={`signal-band${active ? ' active' : ''}`}>
              <span className="swatch" style={{ background: b.color }} />
              <span className="grade">{t(`legend.${b.key}`)}</span>
              <span className="range">
                {b.min}{upper ? `…${upper}` : '+'} dBm
              </span>
            </div>
          );
        })}
      </div>
      {peakDbm != null && (
        <div className="signal-legend-peak">
          {t('legend.peak')}: <b>{peakDbm.toFixed(0)} dBm</b> ·{' '}
          <b style={{ color: gradeForDbm(peakDbm).color }}>
            {t(`legend.${gradeForDbm(peakDbm).key}`)}
          </b>
        </div>
      )}
    </div>
  );
}
