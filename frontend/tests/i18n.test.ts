/**
 * Translation coverage.
 *
 * French-speaking field technicians and public-safety planners are a
 * first-class target audience, and DashNav ships them an EN/FR switch — but
 * four of the five routes had zero t() calls, so switching to French left them
 * an English product on their own pages. These guards keep the two locales in
 * lockstep and keep the wired routes wired.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const ROOT = path.resolve(__dirname, '..');
const load = (loc: string) =>
  JSON.parse(fs.readFileSync(path.join(ROOT, 'locales', loc, 'common.json'), 'utf8'));

function flatten(obj: Record<string, unknown>, prefix = ''): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(obj)) {
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      Object.assign(out, flatten(v as Record<string, unknown>, `${prefix}${k}.`));
    } else {
      out[`${prefix}${k}`] = String(v);
    }
  }
  return out;
}

describe('locale files', () => {
  const en = flatten(load('en'));
  const fr = flatten(load('fr'));

  it('define exactly the same keys in both languages', () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(fr).sort());
  });

  it('have no empty translation', () => {
    const blank = Object.entries({ en, fr })
      .flatMap(([loc, map]) => Object.entries(map)
        .filter(([, v]) => v.trim() === '')
        .map(([k]) => `${loc}:${k}`));
    expect(blank).toEqual([]);
  });

  it('keep interpolation placeholders identical across languages', () => {
    // A {{count}} that survives in English but not in French renders the raw
    // token to the user.
    const mismatched: string[] = [];
    for (const key of Object.keys(en)) {
      const tokens = (s: string) => (s.match(/\{\{\s*\w+\s*\}\}/g) ?? []).sort().join(',');
      if (tokens(en[key]) !== tokens(fr[key] ?? '')) mismatched.push(key);
    }
    expect(mismatched).toEqual([]);
  });
});

describe('routes are wired to the translator', () => {
  // Regression: these shipped entirely in English while the locale files were
  // at full parity, so the strings existed and were simply never used.
  const wired = [
    'app/field/page.tsx',
    'app/dashboard/page.tsx',
    'app/pitch/page.tsx',
    'components/AuthPanel.tsx',
    'components/MapView.tsx',
    'components/ProfileChart.tsx',
    'components/LiveOps.tsx',
    'app/page.tsx',
  ];
  it.each(wired)('%s calls the translator', (rel) => {
    const src = fs.readFileSync(path.join(ROOT, rel), 'utf8');
    expect(src).toMatch(/useTranslation\(/);
    expect((src.match(/\bt\(['"]/g) ?? []).length).toBeGreaterThan(3);
  });
});
