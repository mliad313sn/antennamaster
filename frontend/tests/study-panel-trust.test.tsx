/**
 * Trust regressions in the Radio study panel.
 *
 * Both of these let the panel display one set of parameters while running a
 * different one — the worst class of defect for a tool whose output is a
 * client deliverable, because the wrong number is confident and invisible.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import StudyPanel from '@/components/StudyPanel';
import type { ScenarioResolved } from '@/lib/types';

const TECHS = [
  { key: 'wifi5', label: 'Wi-Fi 5 GHz', generation: 'WLAN', freq_mhz: 5800,
    tx_power_dbm: 23, tx_gain_dbi: 6, rx_gain_dbi: 3, losses_db: 1,
    rx_sensitivity_dbm: -82, h_bs_m: 10, h_ut_m: 3, model: 'fspl',
    environment: 'open' },
  { key: 'tetra400', label: 'TETRA 400', generation: 'PMR', freq_mhz: 400,
    tx_power_dbm: 40, tx_gain_dbi: 9, rx_gain_dbi: 0, losses_db: 3,
    rx_sensitivity_dbm: -103, h_bs_m: 30, h_ut_m: 1.5,
    model: 'okumura_hata', environment: 'urban' },
];

const EQUIPMENT = [{
  id: 'ap-1', model: 'Enterprise Wi-Fi AP', category: 'Wi-Fi',
  band_label: '5 GHz', technology: 'wifi5', model_key: 'fspl',
  environment: 'open', freq_mhz: 5800, tx_power_dbm: 23,
  antenna_gain_dbi: 6, rx_sensitivity_dbm: -82, beamwidth_deg: 65,
}];

vi.mock('@/lib/api', () => ({
  fetchTechnologies: () => Promise.resolve(TECHS),
  fetchModels: () => Promise.resolve([
    { key: 'fspl', label: 'Free space', environments: [] },
    { key: 'okumura_hata', label: 'Okumura-Hata', environments: ['urban'] },
  ]),
  fetchAntennas: () => Promise.resolve([]),
  fetchEquipment: () => Promise.resolve({ equipment: EQUIPMENT, categories: ['Wi-Fi'] }),
  simulateCoverageTracked: vi.fn(),
  simulateMultiCoverage: vi.fn(),
  throughputMap: vi.fn(),
  monteCarloTraffic: vi.fn(),
  frequencyPlan: vi.fn(),
  uploadAntenna: vi.fn(),
  friendlyError: (m: string) => m,
  CoverageCancelled: class extends Error {},
}));

function renderPanel(extra: Partial<React.ComponentProps<typeof StudyPanel>> = {}) {
  const onTechnologyChange = vi.fn();
  const props = {
    tx: { lat: 47, lng: 15 }, dxfId: null, txHeight: 20,
    technology: 'wifi5', onTechnologyChange,
    model: null, onModelChange: vi.fn(),
    environment: null, onEnvironmentChange: vi.fn(),
    foliageDepth: 0, onFoliageChange: vi.fn(),
    rainRate: 0, onRainChange: vi.fn(),
    clutterPct: 0, onClutterChange: vi.fn(),
    surfaceOn: false, onSurfaceChange: vi.fn(),
    worldcoverOn: false, onWorldcoverChange: vi.fn(),
    surfaceAvailable: false,
    study: null, coverage: null, onCoverage: vi.fn(),
    ...extra,
  } as React.ComponentProps<typeof StudyPanel>;
  const utils = render(<StudyPanel {...props} />);
  return { ...utils, onTechnologyChange, props };
}

describe('equipment overrides vs the displayed preset', () => {
  beforeEach(() => localStorage.clear());

  it('clears overrides when the technology changes, so the panel cannot show one budget and run another', async () => {
    const { rerender, props } = renderPanel();
    const equipSelect = await screen.findByDisplayValue('— choose equipment (optional) —');

    // Pick a 23 dBm / -82 dBm Wi-Fi AP: the override fields are now populated
    // and the readout is labelled "Effective".
    fireEvent.change(equipSelect, { target: { value: 'ap-1' } });
    await waitFor(() =>
      expect(screen.getByTestId('effective-budget').textContent).toContain('23'));
    expect(screen.getByTestId('override-count')).toBeInTheDocument();

    // Switch to TETRA (preset 40 dBm / -103 dBm, omni). Previously the
    // overrides survived, so the panel printed the TETRA preset while
    // dispatching 23 dBm / -82 dBm inside a 65-degree sector: ~38 dB out.
    const techSelect = screen.getByLabelText('Technology');
    fireEvent.change(techSelect, { target: { value: 'tetra400' } });
    rerender(<StudyPanel {...{ ...props, technology: 'tetra400' }} />);

    await waitFor(() => {
      const shown = screen.getByTestId('effective-budget').textContent ?? '';
      expect(shown).toContain('40');      // the preset actually in force
      expect(shown).toContain('-103');
      expect(shown).not.toContain('23');
      expect(shown).not.toContain('-82');
    });
    // No stale override remains, so nothing is hidden behind the collapsed
    // "Site link budget" section.
    expect(screen.queryByTestId('override-count')).toBeNull();
  });
});

describe('Simple-mode scenario settings', () => {
  it('applies the resolved radius, sector and fade margin, not just the technology', async () => {
    const scenario: ScenarioResolved = {
      id: 'fleet_wifi', technology: 'wifi5', technology_label: 'Wi-Fi 5 GHz',
      study: 'coverage', radius_km: 3, tx_height_m: 12, rx_height_m: 3,
      sector: true, shadow_margin_db: 6,
    };
    renderPanel({ scenario });

    // The backend resolves these per scenario; dropping them meant the guided
    // path ran at the default 8 km radius with a 0 dB margin (a 50%
    // -probability median) where the scenario asked for a 90/95% design.
    await waitFor(() =>
      expect((screen.getByLabelText(/Radius \(km\)/) as HTMLInputElement).value)
        .toBe('3'));
    // Targeted by title: "Fade margin" also appears in the glossary tooltip's
    // aria-label, so a label query matches two elements.
    expect((screen.getByTitle(/Log-normal shadowing margin/) as HTMLInputElement)
      .value).toBe('6');
  });
});
