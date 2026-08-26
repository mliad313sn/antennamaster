/**
 * Accessibility regressions.
 *
 * Screen-reader and keyboard-only users could not complete a single journey:
 * the frontend had exactly one live region in total, so a study ran for half a
 * minute in silence and every failure appeared in an inert <div>; and the
 * indoor DAS tab could only be driven by clicking a bare <img>, which left its
 * Run button disabled forever without a mouse. Duplicate ids also stripped the
 * accessible name from every repeated row in the DXF wizard and the DAS list.
 */
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';

import StudyPanel from '@/components/StudyPanel';

vi.mock('@/lib/api', () => ({
  fetchTechnologies: () => Promise.resolve([{
    key: 'wifi5', label: 'Wi-Fi 5 GHz', generation: 'WLAN', freq_mhz: 5800,
    tx_power_dbm: 23, tx_gain_dbi: 6, rx_gain_dbi: 3, losses_db: 1,
    rx_sensitivity_dbm: -82, h_bs_m: 10, h_ut_m: 3, model: 'fspl',
    environment: 'open',
  }]),
  fetchModels: () => Promise.resolve([{ key: 'fspl', label: 'Free space', environments: [] }]),
  fetchAntennas: () => Promise.resolve([]),
  fetchEquipment: () => Promise.resolve({ equipment: [], categories: [] }),
  simulateCoverageTracked: vi.fn().mockResolvedValue({
    coverage_id: 'x1', png_url: '/api/rf/coverage/x1.png',
    bounds: [[46.9, 14.9], [47.1, 15.1]], legend: [], warnings: [],
    stats: {
      served_area_fraction: 0.78, max_rx_power_dbm: -61, radius_m: 8000,
      tx_elevation_m: 400, n_radials: 180, n_steps: 100, sites: null,
    },
  }),
  simulateMultiCoverage: vi.fn(),
  throughputMap: vi.fn(),
  monteCarloTraffic: vi.fn(),
  frequencyPlan: vi.fn(),
  uploadAntenna: vi.fn(),
  friendlyError: (m: string) => m,
  CoverageCancelled: class extends Error {},
}));

function panel() {
  return render(<StudyPanel
    tx={{ lat: 47, lng: 15 }} dxfId={null} txHeight={20}
    technology="wifi5" onTechnologyChange={vi.fn()}
    model={null} onModelChange={vi.fn()}
    environment={null} onEnvironmentChange={vi.fn()}
    foliageDepth={0} onFoliageChange={vi.fn()}
    rainRate={0} onRainChange={vi.fn()}
    clutterPct={0} onClutterChange={vi.fn()}
    surfaceOn={false} onSurfaceChange={vi.fn()}
    worldcoverOn={false} onWorldcoverChange={vi.fn()}
    surfaceAvailable={false}
    study={null} coverage={null} onCoverage={vi.fn()}
  />);
}

describe('assistive-technology status (WCAG 4.1.3)', () => {
  it('exposes a polite live region that announces the outcome of a run', async () => {
    panel();
    const status = await screen.findByTestId('study-status');
    expect(status).toHaveAttribute('role', 'status');
    expect(status).toHaveAttribute('aria-live', 'polite');
    // Empty until something happens, so nothing is announced on load.
    expect(status.textContent).toBe('');

    const run = await screen.findByRole('button', { name: /Simulate coverage from TX/ });
    run.click();

    // The user hears that it started, and then what it found — instead of
    // pressing Run and waiting in total silence.
    await waitFor(() =>
      expect(screen.getByTestId('study-status').textContent)
        .toMatch(/78% of the area served/));
    expect(screen.getByTestId('study-status').textContent).toMatch(/-61 dBm/);
  });
});

describe('error surfaces are announced', () => {
  it('marks every error box as an alert', async () => {
    // Sampled across the app rather than per-component: the property that
    // matters is that no error can appear silently anywhere.
    const fs = await import('node:fs');
    const path = await import('node:path');
    const roots = ['components', 'app'];
    const offenders: string[] = [];
    const walk = (dir: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) { walk(full); continue; }
        if (!entry.name.endsWith('.tsx')) continue;
        const src = fs.readFileSync(full, 'utf8');
        const re = /className="error-box"(.{0,60})/g;
        let m: RegExpExecArray | null;
        // eslint-disable-next-line no-cond-assign
        while ((m = re.exec(src)) !== null) {
          if (!m[1].includes('role=')) offenders.push(`${full}: ${m[0].slice(0, 60)}`);
        }
      }
    };
    roots.forEach((r) => walk(path.resolve(__dirname, '..', r)));
    expect(offenders).toEqual([]);
  });
});
