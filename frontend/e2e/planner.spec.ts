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

/**
 * Dismiss the first-run guided tour and prove it really let go.
 *
 * Its overlay covers the whole page while open, so anything that races the
 * dismissal fails later in a confusing place - a click that simply never
 * reaches the map. `locator.isVisible()` resolves immediately (its timeout
 * option is a no-op), so the previous `if (await skip.isVisible(...))` was a
 * coin flip: when the tour had not rendered yet the skip was silently
 * skipped and the tour stayed open on step 1.
 */
async function dismissTour(page: import('@playwright/test').Page) {
  const skip = page.getByRole('button', { name: /^Skip$/ });
  await skip.waitFor({ state: 'visible', timeout: 20000 });
  await skip.click();
  // The tour must release the page, not just hide its tooltip.
  await expect(page.locator('.react-joyride__overlay')).toHaveCount(0);
}

/**
 * Enter Expert mode.
 *
 * A first run now starts in the guided Simple mode - that is the whole point
 * of it, and it deliberately hides the propagation model, the technology
 * select and every other RF knob. The tests below exercise the expert
 * journey, so they have to ask for it rather than assuming the default.
 */
async function goExpert(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: 'Expert', exact: true }).click();
  await expect(page.getByLabel('Technology')).toBeVisible();
}

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
      await dismissTour(page);
      await goExpert(page);

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
      await expect(map).toBeVisible();
      const box = (await map.boundingBox())!;
      // Offset from centre: the TX pin sits exactly there and would swallow
      // the click. ~60 px is roughly 3 km at the default zoom, so the point
      // stays inside the 8 km study radius. Clicking through the locator (not
      // raw mouse coordinates) waits for actionability and names whatever
      // overlay intercepts the click if one ever does.
      const reading = page.waitForResponse(
        (r) => /\/api\/rf\/coverage\/[^/]+\/at\?/.test(r.url()),
        { timeout: 30000 });
      await map.click({ position: { x: box.width / 2 + 60,
                                    y: box.height / 2 - 40 } });
      // Wait for the point query itself, so the assertion below is about
      // rendering rather than about how fast the network happened to be.
      expect((await reading).status()).toBe(200);

      const popup = page.locator('.leaflet-popup-content');
      await expect(popup).toBeVisible({ timeout: 20000 });
      await expect(popup).toContainText('Signal here');
      // A real number, in dBm — not just a colour swatch.
      await expect(popup).toContainText(/-?\d+(\.\d+)?\s*dBm/);
      await expect(popup).toContainText(/km @/);
    });

  test('the sidebar can be rearranged and the layout survives a reload',
    async ({ page }) => {
      await dismissTour(page);
      await goExpert(page);

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

  test('a first-time visitor lands in the guided mode and can still get an answer',
    async ({ page }) => {
      // Simple mode is the default on a first run, and it must be a complete
      // path in itself: it used to be purely additive, hiding nothing, so a
      // non-RF user was handed the full expert sidebar. It must now show the
      // scenario picker and a small surface - but still reach a result.
      await dismissTour(page);

      await expect(page.getByRole('button', { name: 'Simple', exact: true }))
        .toHaveClass(/active/);

      // The RF knobs are gone.
      await expect(page.getByLabel('Technology')).toHaveCount(0);
      await expect(page.getByLabel('Propagation model')).toHaveCount(0);
      const fields = page.locator('.sidebar input, .sidebar select, .sidebar textarea');
      expect(await fields.count()).toBeLessThanOrEqual(6);

      // Choosing an outcome configures the radio for the user. The scenario
      // cards are themselves the buttons; picking one reveals the confirm.
      await page.getByRole('button', { name: /Wi-Fi for a vehicle fleet/i }).click();
      await page.getByRole('button', { name: /Set this up/i }).click();
      await expect(page.getByText(/place your points on the map/i)).toBeVisible();

      // ...and the study is runnable without ever naming a technology.
      await page.getByLabel('TX lat').fill('47.0');
      await page.getByLabel('TX lon').fill('15.0');
      const simulate = page.getByRole('button', { name: /Simulate coverage from TX/i });
      await expect(simulate).toBeEnabled();
    });
});
