/**
 * The planner on a phone.
 *
 * Field technicians and ops leads are a target audience and the responsive
 * breakpoint was written for them, but the layout was unusable: the desktop
 * shell pins .app-shell to the viewport and gives BOTH .app-main and .sidebar
 * their own overflow, the sidebar with overscroll-behavior: contain. Stacked
 * on a 390x844 screen that produced ~893px of content in a ~546px box whose
 * scroll could not be reached — the sidebar swallowed the gesture instead of
 * chaining to its parent and Leaflet consumed every touch over the map — so
 * the elevation profile sat at y=847 with no way to get to it.
 *
 * These run under the `mobile` Playwright project (Pixel 5).
 */
import { expect, test } from '@playwright/test';

async function dismissTour(page: import('@playwright/test').Page) {
  const skip = page.getByRole('button', { name: /^Skip$/ });
  await skip.waitFor({ state: 'visible', timeout: 20000 });
  await skip.click();
  await expect(page.locator('.react-joyride__overlay')).toHaveCount(0);
}

test.describe('planner at phone width', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await dismissTour(page);
  });

  test('never scrolls sideways', async ({ page }) => {
    // A horizontal scrollbar on a phone means something overflows its column;
    // it is the single clearest signal of a broken responsive layout.
    const { scrollWidth, clientWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1);
  });

  test('the whole page is reachable by scrolling the document', async ({ page }) => {
    // The fix is structural: on small screens the document itself scrolls,
    // rather than an inner box whose scroll no gesture can reach.
    const scrollable = await page.evaluate(() =>
      document.documentElement.scrollHeight > document.documentElement.clientHeight);
    expect(scrollable).toBe(true);

    // The map sits below the fold once the sidebar lays out inline, so
    // reaching it is the real test of "the page can be scrolled".
    const map = page.locator('.map-wrap');
    await expect(map).not.toBeInViewport();
    await map.scrollIntoViewIfNeeded();
    await expect(map).toBeInViewport();
  });

  test('the sidebar does not trap the scroll in its own box', async ({ page }) => {
    // overscroll-behavior: contain plus its own overflow made the sidebar a
    // dead end on touch. At phone width it must lay out inline instead.
    const trapped = await page.evaluate(() => {
      const el = document.querySelector('.sidebar');
      if (!el) return 'no sidebar';
      const cs = getComputedStyle(el);
      return `${cs.overflowY}/${cs.overscrollBehaviorY}`;
    });
    expect(trapped).not.toMatch(/^(auto|scroll)\//);
  });

  test('controls are big enough for a gloved hand', async ({ page }) => {
    // WCAG 2.5.8 asks 24px; a tower base asks for considerably more. The
    // field view already did this and the planner never inherited it.
    const small = await page.evaluate(() => {
      const out: string[] = [];
      document.querySelectorAll('.sidebar button, .sidebar input, .sidebar select')
        .forEach((el) => {
          const r = (el as HTMLElement).getBoundingClientRect();
          // Skip anything not laid out, and the deliberately compact
          // drag/visibility icons in the panel arranger.
          if (r.height === 0) return;
          if ((el as HTMLElement).closest('.sortable-controls')) return;
          if (r.height < 40) out.push(`${el.tagName}.${(el as HTMLElement).className} ${r.height}px`);
        });
      return out;
    });
    expect(small).toEqual([]);
  });

  test('the 2D/3D toggle is actually clickable, not buried under a map control', async ({ page }) => {
    // .view-toggle sat at z-index 500 under Leaflet's .leaflet-top (1000),
    // so the headline 3D feature was covered at every width.
    const buttons = page.locator('.view-toggle button');
    await expect(buttons).toHaveCount(2);
    // elementFromPoint works in VIEWPORT coordinates, so the control has to
    // be on screen before asking what is on top of it.
    await page.locator('.view-toggle').scrollIntoViewIfNeeded();
    const hits = await page.evaluate(() => {
      const out: boolean[] = [];
      document.querySelectorAll('.view-toggle button').forEach((el) => {
        const r = el.getBoundingClientRect();
        const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        out.push(el.contains(top as Node) || el === top);
      });
      return out;
    });
    expect(hits).toEqual([true, true]);
    // And it really responds, rather than merely being hit-testable.
    await buttons.nth(1).click();
    await expect(page.locator('.view-toggle button.active')).toHaveText(/3D/);
  });
});
