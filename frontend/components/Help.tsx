'use client';

/** Inline glossary tooltips: hover/tap the ⓘ next to a physics parameter to
 *  get a plain-language definition — education for less technical users. */

const GLOSSARY: Record<string, string> = {
  fresnel: 'Fresnel zone: the rugby-ball-shaped region around the direct ray '
    + 'that carries most of the radio energy. Keep ~60% of the first zone '
    + 'clear of terrain/obstacles or the link degrades even with line of sight.',
  fspl: 'Free-space path loss: signal spreading loss in empty space. It grows '
    + '+6 dB every time distance (or frequency) doubles — the baseline every '
    + 'real-world model adds losses on top of.',
  kfactor: 'k-factor: how much the atmosphere bends radio waves. k = 4/3 '
    + '(standard refraction) makes Earth look flatter to radio than to the eye; '
    + 'k < 1 (worst case) bulges terrain up into the path.',
  fade_margin: 'Fade margin: extra dB reserved for signal variability '
    + '(shadowing, weather). ~5.5 dB gives ~90% area reliability, ~8 dB ≈ 95%. '
    + 'Zero margin means the median barely reaches — half of locations fail.',
  eirp: 'EIRP: transmit power plus antenna gain minus cable losses — the '
    + 'power the antenna effectively radiates toward the receiver.',
  sensitivity: 'Receiver sensitivity: the weakest signal (dBm) the radio can '
    + 'still decode. Derived from thermal noise (kTB), channel bandwidth, '
    + 'receiver noise figure and the SINR the modulation needs.',
  downtilt: 'Downtilt: pointing the antenna beam below the horizon to focus '
    + 'coverage near the site and reduce interference/overshoot. The #1 knob '
    + 'for shaping a cell.',
  deygout: 'Deygout diffraction: estimates the dB lost when hills/buildings '
    + 'block the path, by treating the strongest obstacles as knife edges '
    + '(up to 3, recursively).',
  provenance: 'Data provenance: which elevation source produced each profile '
    + 'sample — global SRTM (blue) or your uploaded DXF survey (orange).',
  helmert: 'Helmert transform: a scale + rotation + shift solved from your '
    + 'control-point pairs; the residual (m) says how well the points agree — '
    + 'large residuals mean a mis-picked point or wrong units.',
  bulge: 'Earth bulge: on long paths the Earth\'s curvature rises between '
    + 'the endpoints; at k=4/3 a 50 km path bulges ~37 m at mid-path.',
};

export default function Help({ term }: { term: keyof typeof GLOSSARY | string }) {
  const text = GLOSSARY[term];
  if (!text) return null;
  return (
    <span className="help-tip" tabIndex={0} role="note" aria-label={text}>
      ⓘ<span className="help-pop">{text}</span>
    </span>
  );
}
