/**
 * Component smoke + heavy-prop tests: the chart must absorb a 2,048-point
 * profile without exploding the DOM, the map must mount with full props
 * (Leaflet mocked for jsdom), and the dashboards/wizard must render.
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';

import Help from '@/components/Help';
import ProfileChart, { downsample } from '@/components/ProfileChart';
import type { ProfilePoint, ProfileResponse } from '@/lib/types';

// ---- Leaflet mocks (jsdom has no real layout/canvas) -----------------------
vi.mock('leaflet', () => ({
  default: {
    divIcon: () => ({}),
    latLngBounds: (a: unknown, b: unknown) => ({ a, b, pad: () => ({}) }),
  },
}));
vi.mock('react-leaflet', () => {
  const Stub = ({ children }: { children?: React.ReactNode }) =>
    React.createElement('div', { 'data-testid': 'leaflet-stub' }, children);
  return {
    MapContainer: Stub, TileLayer: Stub, Marker: Stub, Popup: Stub,
    Polygon: Stub, Polyline: Stub, ImageOverlay: Stub,
    LayersControl: Object.assign(Stub, { BaseLayer: Stub }),
    useMap: () => ({ fitBounds: vi.fn(), flyTo: vi.fn(), getZoom: () => 11 }),
    useMapEvents: () => null,
  };
});

function makeProfile(n: number): ProfileResponse {
  const points: ProfilePoint[] = Array.from({ length: n }, (_, i) => ({
    d: i * 50, lat: 47 + i * 1e-4, lon: 15 + i * 1e-4,
    elev: 400 + 80 * Math.sin(i / 40),
    elev_curved: 401 + 80 * Math.sin(i / 40),
    los: 500 + i * 0.05, fresnel_lower: 480 + i * 0.05,
    source: i % 3 ? 'srtm' : 'dxf', dxf_weight: i % 3 ? 0 : 1,
    rx_power_dbm: -60 - i * 0.02,
  }));
  return {
    samples: n, dxf_id: null, distance_m: n * 50, study: null, points,
    rf: {
      line_of_sight_clear: false, fresnel_clearance_ratio: -0.4,
      knife_edge_loss_db: 12.2, worst_obstruction_index: Math.floor(n / 2),
      worst_obstruction_v: 1.4, k_factor: 4 / 3, freq_mhz: 446,
      tx_height_m: 20, rx_height_m: 10,
    },
  };
}

describe('ProfileChart under heavy props', () => {
  it('downsamples 2048 points to <=514 while keeping peaks and endpoints', () => {
    const pts = makeProfile(2048).points;
    // Plant a spike that naive striding would drop.
    pts[1337].elev_curved = 9999;
    const out = downsample(pts);
    expect(out.length).toBeLessThanOrEqual(514);
    expect(out[0]).toBe(pts[0]);
    expect(out[out.length - 1]).toBe(pts[pts.length - 1]);
    expect(Math.max(...out.map((p) => p.elev_curved))).toBe(9999);
  });

  it('renders a 2048-point profile without crashing', () => {
    const { container } = render(<ProfileChart profile={makeProfile(2048)} />);
    expect(container.textContent).toContain('Elevation profile');
    expect(container.textContent).toContain('Path obstructed');
  });

  it('renders a minimal 2-point profile', () => {
    render(<ProfileChart profile={makeProfile(2)} />);
    expect(screen.getByText(/Elevation profile/)).toBeInTheDocument();
  });
});

describe('MapView with full props', () => {
  it('mounts with coverage + georef + markers (mocked Leaflet)', async () => {
    const { default: MapView } = await import('@/components/MapView');
    const { container } = render(
      <MapView
        tx={{ lat: 47, lng: 15 }} rx={{ lat: 47.1, lng: 15.1 }}
        placing={null} onPlace={() => {}}
        georef={{
          dxf_id: 'x', transform: { mode: 'origin_bearing' },
          grid: { nx: 46, ny: 46, cell_size_m: 26.7, points_used: 500 },
          footprint: [[47, 15], [47, 15.01], [47.01, 15.01], [47.01, 15]],
          overlay_bounds: [[47, 15], [47.01, 15.01]],
          overlay_url: '/api/dxf/x/overlay.png',
          validation: { warning: null },
        }}
        showOverlay coverage={{
          coverage_id: 'c', png_url: '/api/rf/coverage/c.png',
          bounds: [[46.9, 14.9], [47.1, 15.1]], legend: [],
          stats: { served_area_fraction: 0.5, radius_m: 10000,
                   tx_elevation_m: 400, max_rx_power_dbm: -40 },
          technology: {} as never, warnings: [],
        }}
      />,
    );
    expect(container.querySelectorAll('[data-testid="leaflet-stub"]').length)
      .toBeGreaterThan(3);
  });
});

describe('Help glossary', () => {
  it('renders a definition for known terms and nothing for unknown', () => {
    render(<Help term="fresnel" />);
    expect(screen.getByRole('note')).toBeInTheDocument();
    const { container } = render(<Help term="nonsense" />);
    expect(container.querySelector('.help-tip')).toBeNull();
  });
});

describe('Dashboards render', () => {
  it('Command Center renders signed-out state', async () => {
    const { default: Dashboard } = await import('@/app/dashboard/page');
    render(<Dashboard />);
    expect((await screen.findAllByText(/Command Center|Sign in/)).length).toBeGreaterThan(0);
  });

  it('Pitch page renders scenario cards', async () => {
    const { default: Pitch } = await import('@/app/pitch/page');
    render(<Pitch />);
    expect(await screen.findByText('Option A')).toBeInTheDocument();
    expect(await screen.findByText('Option B')).toBeInTheDocument();
  });

  it('DxfWizard shows the drop zone', async () => {
    const { default: DxfWizard } = await import('@/components/DxfWizard');
    render(<DxfWizard onClose={() => {}} onGeoreferenced={() => {}} />);
    expect(screen.getByText(/Drop your DXF here/)).toBeInTheDocument();
  });
});

describe('Study & Indoor panels render', () => {
  it('StudyPanel renders with no technology selected', async () => {
    const { default: StudyPanel } = await import('@/components/StudyPanel');
    render(
      <StudyPanel
        tx={{ lat: 47, lng: 15 }} dxfId={null} txHeight={20}
        technology={null} onTechnologyChange={() => {}}
        model={null} onModelChange={() => {}}
        environment={null} onEnvironmentChange={() => {}}
        foliageDepth={0} onFoliageChange={() => {}}
        rainRate={0} onRainChange={() => {}}
        clutterPct={0} onClutterChange={() => {}}
        surfaceOn={false} onSurfaceChange={() => {}}
        surfaceAvailable={false}
        study={null} coverage={null} onCoverage={() => {}}
      />,
    );
    expect(screen.getByText('Radio study')).toBeInTheDocument();
  });

  it('IndoorStudio renders its three tabs', async () => {
    const { default: IndoorStudio } = await import('@/components/IndoorStudio');
    render(<IndoorStudio onClose={() => {}} />);
    expect(screen.getByText('Tunnel link')).toBeInTheDocument();
    expect(screen.getByText('Through-the-earth')).toBeInTheDocument();
  });
});
