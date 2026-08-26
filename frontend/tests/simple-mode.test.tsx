/**
 * Simple mode must actually simplify.
 *
 * Regression: the guided mode was purely additive — it prepended a scenario
 * grid and still rendered all eight expert panels, including the ~25-control
 * Radio study panel — and the app booted in Expert, so every first-time
 * visitor was handed exactly what Simple mode exists to prevent.
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import StudyPanel from '@/components/StudyPanel';

const TECHS = [{
  key: 'wifi5', label: 'Wi-Fi 5 GHz', generation: 'WLAN', freq_mhz: 5800,
  tx_power_dbm: 23, tx_gain_dbi: 6, rx_gain_dbi: 3, losses_db: 1,
  rx_sensitivity_dbm: -82, h_bs_m: 10, h_ut_m: 3, model: 'fspl',
  environment: 'open',
}];

vi.mock('@/lib/api', () => ({
  fetchTechnologies: () => Promise.resolve(TECHS),
  fetchModels: () => Promise.resolve([{ key: 'fspl', label: 'Free space', environments: [] }]),
  fetchAntennas: () => Promise.resolve([]),
  fetchEquipment: () => Promise.resolve({
    equipment: [{
      id: 'ap-1', model: 'AP', category: 'Wi-Fi', band_label: '5 GHz',
      technology: 'wifi5', model_key: 'fspl', environment: 'open',
      freq_mhz: 5800, tx_power_dbm: 23, antenna_gain_dbi: 6,
      rx_sensitivity_dbm: -82, beamwidth_deg: 65,
    }],
    categories: ['Wi-Fi'],
  }),
  simulateCoverageTracked: vi.fn(),
  simulateMultiCoverage: vi.fn(),
  throughputMap: vi.fn(),
  monteCarloTraffic: vi.fn(),
  frequencyPlan: vi.fn(),
  uploadAntenna: vi.fn(),
  friendlyError: (m: string) => m,
  CoverageCancelled: class extends Error {},
}));

function panel(compact: boolean) {
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
    compact={compact}
    study={null} coverage={null} onCoverage={vi.fn()}
  />);
}

describe('Simple (guided) mode', () => {
  beforeEach(() => localStorage.clear());

  it('hides the RF knobs but still lets the user run the study', async () => {
    const { container } = panel(true);
    // Wait for the async catalogue fetches to settle.
    await screen.findByRole('button', { name: /Simulate coverage from TX/ });

    // The whole point: a non-RF user is not asked about propagation models,
    // antenna patterns, downtilt, clutter or link budgets.
    for (const gone of [/Technology/, /Propagation model/, /Antenna pattern/,
                        /Downtilt/, /Fade margin/, /Clutter/,
                        /Site link budget/, /Equipment/]) {
      expect(screen.queryByLabelText(gone)).toBeNull();
      expect(screen.queryByRole('button', { name: gone })).toBeNull();
    }
    // Multi-site, frequency planning and capacity are expert workflows.
    expect(screen.queryByRole('button', { name: /Add current TX as site/ })).toBeNull();

    // A guided user is left with a very small surface.
    const fields = container.querySelectorAll('input, select, textarea');
    expect(fields.length).toBeLessThanOrEqual(6);
  });

  it('keeps every expert control when not compact', async () => {
    panel(false);
    expect(await screen.findByLabelText(/Technology/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Propagation model/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Add current TX as site/ })).toBeInTheDocument();
  });
});
