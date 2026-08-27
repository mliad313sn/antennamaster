/**
 * The payback on the pitch screen must not contradict the coverage printed
 * next to it.
 *
 * Measured on the running app: Option A's KPI row read "10% SERVED AREA" and
 * "5.9 mo PAYBACK / +$394k" side by side. The ROI used only the revenue the
 * user typed and the equipment cost — the served-area fraction never entered
 * it. So a design covering a tenth of the target site, which is a design that
 * failed, was presented to a buyer with an attractive payback; and Option B,
 * covering seven times more area, was credited with nothing for it. Their
 * paybacks differed only because their radios cost different amounts.
 *
 * This is the same failure the study-of-record work exists to prevent — a
 * number that can disagree with the evidence beside it — and it sat on the
 * one screen built to persuade someone.
 *
 * The model here is the honest minimum: revenue is earned where there is
 * coverage, so it scales with the served fraction, and the card says so in
 * words. These tests pin that relationship, not the exact currency figures.
 */
import { describe, expect, it } from 'vitest';

import { roi } from '@/lib/roi';

const COSTS = { capex_total_usd: 40_000, opex_total_year_usd: 12_000,
                tco_5y_usd: 100_000 };
const REVENUE = 8_000;
const months = (s: string) => parseFloat(s);

describe('payback answers to the coverage it is shown beside', () => {
  it('reproduces the case measured on screen: 10% served vs 72% served', () => {
    // The two options the pitch screen actually compared. Before the fix both
    // reported a payback of a few months, differing only by equipment cost.
    const poor = roi(REVENUE, COSTS, 0.10);
    const good = roi(REVENUE, COSTS, 0.72);
    // At 10% served the revenue earned ($800/mo) does not even meet the
    // running costs ($1000/mo). There is no payback, and the screen now says
    // so instead of quoting 5.9 months next to "10% SERVED AREA".
    expect(poor.payback).toBe('never');
    expect(months(good.payback)).toBeGreaterThan(0);
    expect(months(good.payback)).toBeLessThan(60);
  });

  it('ranks two viable options by their coverage', () => {
    const worse = roi(REVENUE, COSTS, 0.40);
    const better = roi(REVENUE, COSTS, 0.90);
    expect(months(worse.payback)).toBeGreaterThan(months(better.payback));
  });

  it('better coverage cannot make the payback worse', () => {
    let previous = Infinity;
    for (const served of [0.2, 0.4, 0.6, 0.8, 1.0]) {
      const m = months(roi(REVENUE, COSTS, served).payback);
      expect(m).toBeLessThanOrEqual(previous);
      previous = m;
    }
  });

  it('refuses to state a payback when the coverage is unknown', () => {
    // A confident figure with nothing behind it is worse than a dash: this
    // screen is shown to a customer.
    expect(roi(REVENUE, COSTS, null)).toEqual({ payback: '—', y5: '—' });
    expect(roi(REVENUE, null, 0.5)).toEqual({ payback: '—', y5: '—' });
  });

  it('says "never" when the served area cannot even cover the running costs', () => {
    // 5% of $8k/mo is $400, against $1000/mo of OPEX. There is no payback,
    // and inventing one by ignoring coverage is exactly the old bug.
    expect(roi(REVENUE, COSTS, 0.05).payback).toBe('never');
  });

  it('renders a loss as −$36k, not $-36k', () => {
    // Observed on screen: the 10%-coverage option's 5-year net printed as
    // "$-36k". On a slide in front of a customer that reads like a typo.
    const loss = roi(REVENUE, COSTS, 0.15);   // pays back, but not within 5 years
    expect(loss.y5.startsWith('−$')).toBe(true);
    expect(loss.y5).not.toContain('$-');
  });

  it('full coverage reproduces the old, unscaled figures', () => {
    // The change is not a re-scaling of the whole model - at 100% served it
    // is the previous calculation exactly, so the numbers a user already
    // trusts for a fully-covering design do not move.
    const full = roi(REVENUE, COSTS, 1.0);
    const monthly = REVENUE - COSTS.opex_total_year_usd / 12;
    expect(full.payback).toBe(`${(COSTS.capex_total_usd / monthly).toFixed(1)} mo`);
  });
});
