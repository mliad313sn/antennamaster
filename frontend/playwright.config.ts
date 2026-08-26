/**
 * Browser-level tests for the planner.
 *
 * Boots the real backend and a production build of the web app, so the tests
 * exercise the same code path a user gets — no mocked fetch, no stubbed map.
 * Chromium is expected to be preinstalled (PLAYWRIGHT_BROWSERS_PATH); we never
 * download one here so the suite works offline.
 */
import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.E2E_PORT ?? 3111);
// Must match the backend URL baked into the build (next.config.mjs resolves
// rewrites at build time), so the e2e stack proxies exactly like a real
// deployment does. Override both together if you rebuild with another value.
const API_PORT = Number(process.env.E2E_API_PORT ?? 8010);

export default defineConfig({
  testDir: './e2e',
  // A cold coverage study fetches real DEM tiles, which is slow the first time.
  timeout: 180_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{
    name: 'chromium',
    testIgnore: /mobile\.spec\.ts/,
    use: {
      ...devices['Desktop Chrome'],
      // Use a preinstalled Chromium when one is provided (CI images and
      // sandboxes ship one whose build number rarely matches the npm
      // package's expectation). Set E2E_CHROMIUM to override; unset falls
      // back to Playwright's own download.
      launchOptions: process.env.E2E_CHROMIUM
        ? { executablePath: process.env.E2E_CHROMIUM }
        : {},
    },
  }, {
    // The planner is meant for field technicians on phones and rugged
    // tablets, and it was unusable there: the elevation profile sat at y=847
    // on a 740px screen behind three nested scrollers with no reachable outer
    // scroll. Only a real device viewport catches that, so it is now gated.
    name: 'mobile',
    testMatch: /mobile\.spec\.ts/,
    use: {
      ...devices['Pixel 5'],
      launchOptions: process.env.E2E_CHROMIUM
        ? { executablePath: process.env.E2E_CHROMIUM }
        : {},
    },
  }],
  webServer: [
    {
      command: `python -m uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT}`,
      cwd: '../backend',
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      // Never reuse: a server left over from an earlier build happily
      // serves stale HTML whose chunk hashes no longer exist, which shows up
      // as a ChunkLoadError and a blank page - i.e. as a phantom app bug.
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      // `npm start` runs the standalone server (next start is unsupported with
      // output: 'standalone' and cannot serve the client chunks).
      command: 'npm start',
      url: `http://127.0.0.1:${PORT}`,
      reuseExistingServer: false,
      timeout: 180_000,
      env: { PORT: String(PORT) },
    },
  ],
});
