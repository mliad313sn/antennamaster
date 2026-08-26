/**
 * End-to-end smoke test of the core planning loop, in a real browser against
 * a real backend.
 *
 * Everything else in the suite mocks something: vitest mocks fetch and stubs
 * Leaflet, and the backend tests never render a pixel. That leaves the actual
 * user journey — the one thing that must never break — untested. This drives
 * it the way a planner does: place a site, run a study, watch it progress,
 * read the result, then click the map to inspect a point.
 *
 * Run with `npm run e2e` (playwright.config.ts boots both servers).
 */
import { expect, test } from '@playwright/test';

test.describe('the core planning loop', () => {
  test.beforeEach(async ({ page }) => {
    // Playwright gives every test a fresh browser context, so localStorage
    // already starts empty. (Do NOT clear it via addInitScript: that runs on
    // every navigation, including page.reload(), which would wipe exactly the
    // persistence the second test is here to verify.)
    await page.goto('/');
  });

  test('place a transmitter, run a coverage study, read a point off the map',
    async ({ page }) => {
      // The guided tour auto-runs for first-time visitors and covers the UI.
      const skip = page.getByRole('button', { name: /skip/i });
      if (await skip.isVisible({ timeout: 8000 }).catch(() => false)) {
        await skip.click();
      }

      // --- place the site by typing exact coordinates (no map maths needed)
      await page.getByLabel('TX lat').fill('47.0');
      await page.getByLabel('TX lon').fill('15.0');

      // --- choose a technology so the study panel becomes operable
      await page.getByLabel('Technology').selectOption('gsm900');

      const simulate = page.getByRole('button', { name: /Simulate coverage from TX/i });
      await expect(simulate).toBeEnabled();

      // --- run it; a queued study must report progress, not freeze
      await simulate.click();
      await expect(page.getByRole('progressbar')).toBeVisible({ timeout: 15000 });

      // --- the study lands: served-area statistic and the 5-class legend
      await expect(page.getByText('Served area')).toBeVisible({ timeout: 90000 });
      await expect(page.getByText(/Excellent \(/)).toBeVisible();
      await expect(page.getByText(/Marginal \(/)).toBeVisible();

      // --- and the coverage raster is actually painted on the map
      const overlay = page.locator('.leaflet-image-layer');
      await expect(overlay).toHaveCount(1);

      // --- click the map to read the predicted level at that point
      await expect(page.getByText(/Click anywhere on the coverage/i)).toBeVisible();
      const map = page.locator('.leaflet-container');
      const box = (await map.boundingBox())!;
      await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);

      const popup = page.locator('.leaflet-popup-content');
      await expect(popup).toBeVisible({ timeout: 20000 });
      await expect(popup).toContainText('Signal here');
      // A real number, in dBm — not just a colour swatch.
      await expect(popup).toContainText(/-?\d+(\.\d+)?\s*dBm/);
      await expect(popup).toContainText(/km @/);
    });

  test('the sidebar can be rearranged and the layout survives a reload',
    async ({ page }) => {
      const skip = page.getByRole('button', { name: /skip/i });
      if (await skip.isVisible({ timeout: 8000 }).catch(() => false)) {
        await skip.click();
      }

      const panelIds = () => page.locator('[data-panel-id]')
        .evaluateAll((els) => els.map((e) => e.getAttribute('data-panel-id')));

      const before = await panelIds();
      expect(before.length).toBeGreaterThan(3);

      await page.getByRole('button', { name: /Arrange panels/i }).click();
      // Move the first panel down using the keyboard/touch-safe control.
      await page.getByRole('button', { name: /Move .* down/ }).first().click();
      await page.getByRole('button', { name: /^Done$/ }).click();

      const after = await panelIds();
      expect(after[0]).toBe(before[1]);
      expect(after[1]).toBe(before[0]);

      // The whole point of the feature: it is still there tomorrow.
      await page.reload();
      const reloaded = await panelIds();
      expect(reloaded.slice(0, 2)).toEqual(after.slice(0, 2));
    });
});
