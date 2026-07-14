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
  sensitivity: 'Receiver sensitivity: the weakest signal (dBm) the radio can '
    + 'still decode. Derived from thermal noise (kTB), channel bandwidth, '
    + 'receiver noise figure and the SINR the modulation needs.',
  downtilt: 'Downtilt: pointing the antenna beam below the horizon to focus '
    + 'coverage near the site and reduce interference/overshoot. The #1 knob '
    + 'for shaping a cell.',
  deygout: 'Deygout diffraction: estimates the dB lost when hills/buildings '
    + 'block the path, by treating the strongest obstacles as knife edges '
    + '(up to 3, recursively).',
  clutter: 'Clutter (ITU-R P.2108): statistical extra loss from buildings/'
    + 'street furniture the elevation data cannot see. The percentage is the '
    + 'share of locations covered: 50% = median city, 90% = conservative.',
  helmert: 'Helmert transform: a scale + rotation + shift solved from your '
    + 'control-point pairs; the residual (m) says how well the points agree — '
    + 'large residuals mean a mis-picked point or wrong units.',
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
