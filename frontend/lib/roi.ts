/**
 * Return on investment for a deployment option, as shown on the pitch screen.
 *
 * REVENUE IS EARNED WHERE THERE IS COVERAGE, so the served-area fraction
 * scales it. Without that, this returned the same payback for a design that
 * covers the site and one that covers almost none of it: the two differed
 * only by equipment cost, and the option covering seven times more area was
 * credited with nothing for it.
 *
 * Measured on the screen itself before the fix: one option's KPI row read
 * "10% SERVED AREA" and "5.9 mo PAYBACK / +$394k" side by side. A plan
 * covering a tenth of the target is a plan that failed, and it was being
 * handed to a buyer with an attractive payback — a number contradicting the
 * evidence printed next to it, on the one screen built to persuade someone.
 *
 * Scaling is an assumption, not a fact, so the card states it in words
 * underneath. An assumption the reader cannot see is just an unsupported
 * number wearing a different hat.
 *
 * Lives here rather than inside the page component so the relationship it
 * encodes can actually be tested.
 */
export type RoiCosts = {
  capex_total_usd: number;
  opex_total_year_usd: number;
  tco_5y_usd: number;
};

export function roi(revenuePerMonth: number, costs: RoiCosts | null,
                    served: number | null): { payback: string; y5: string } {
  // No coverage figure means no basis for a number. A dash is the honest
  // answer; a confident figure with nothing behind it is worse than none.
  if (!costs || served === null) return { payback: '—', y5: '—' };
  const earned = revenuePerMonth * served;
  const monthly = earned - costs.opex_total_year_usd / 12;
  if (monthly <= 0) return { payback: 'never', y5: '—' };
  const months = costs.capex_total_usd / monthly;
  const y5 = earned * 60 - costs.tco_5y_usd;
  // Sign outside the currency symbol: a negative rendered as "$-36k" reads
  // like a typo on a slide in front of a customer.
  return { payback: `${months.toFixed(1)} mo`,
           y5: `${y5 >= 0 ? '+' : '−'}$${Math.abs(y5 / 1000).toFixed(0)}k` };
}
