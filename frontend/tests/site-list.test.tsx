/**
 * A cluster study must be able to describe the network the customer has.
 *
 * Two gaps: a site could be added and removed but never corrected — a
 * mistyped coordinate meant deleting the row and re-clicking the map — and
 * the per-site radio overrides that make a real multi-layer estate
 * expressible (800 MHz macro + 3.5 GHz capacity + 400 MHz PMR in one study)
 * existed only in the API. The UI cloned one preset across every
 * transmitter, so the composite described a network that does not exist.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import SiteList from '@/components/SiteList';
import { siteBody } from '@/lib/api';
import type { SiteEntry } from '@/lib/types';

const parseSitesCsv = vi.fn();
const exportSitesCsv = vi.fn();

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  parseSitesCsv: (...a: unknown[]) => parseSitesCsv(...a),
  exportSitesCsv: (...a: unknown[]) => exportSitesCsv(...a),
}));

const SITES: SiteEntry[] = [
  { lat: 47.0, lon: 15.0, name: 'Macro N', antenna_azimuth_deg: 0 },
  { lat: 47.1, lon: 15.1, name: 'Small cell 3', antenna_azimuth_deg: null },
];

function mount(sites = SITES) {
  const onChange = vi.fn();
  render(<SiteList sites={sites} onChange={onChange} />);
  return onChange;
}

/** The disclosure control, not the "Remove <name>" button beside it — both
 *  carry the site name. */
function openSite(name: string) {
  const btn = screen.getAllByRole('button', { expanded: false })
    .find((b) => b.textContent?.includes(name));
  fireEvent.click(btn!);
}

beforeEach(() => { parseSitesCsv.mockReset(); exportSitesCsv.mockReset(); });

describe('cluster-study site inventory', () => {
  it('lets a site be corrected instead of deleted and re-placed', () => {
    const onChange = mount();
    openSite('Macro N');

    fireEvent.change(screen.getByLabelText('Latitude'), { target: { value: '47.5' } });
    expect(onChange).toHaveBeenCalled();
    const next = onChange.mock.calls.at(-1)![0] as SiteEntry[];
    expect(next[0].lat).toBe(47.5);
    // ...and only that site changed.
    expect(next[1]).toEqual(SITES[1]);
  });

  it('leaves radio overrides blank, meaning inherit', () => {
    mount();
    openSite('Macro N');
    // A field pre-filled with the inherited number looks like a decision
    // someone made; a planner reading the study later could not tell an
    // override from a default.
    const freq = screen.getByLabelText(/Frequency/) as HTMLInputElement;
    expect(freq.value).toBe('');
    expect(freq.placeholder).toMatch(/inherit/i);
  });

  it('records an override and shows the site now differs from the study', () => {
    const onChange = mount();
    openSite('Macro N');
    fireEvent.change(screen.getByLabelText(/Frequency/), { target: { value: '3500' } });

    const next = onChange.mock.calls.at(-1)![0] as SiteEntry[];
    expect(next[0].freq_mhz).toBe(3500);

    render(<SiteList sites={next} onChange={() => {}} />);
    expect(screen.getAllByText(/1 override/i).length).toBeGreaterThan(0);
  });

  it('clearing an override sends null, not zero', () => {
    // 0 dBm is a real transmit power. An override cleared to 0 would quietly
    // plan a transmitter with no output instead of inheriting the preset.
    const onChange = mount([{ ...SITES[0], tx_power_dbm: 46 }]);
    openSite('Macro N');
    fireEvent.change(screen.getByLabelText(/TX power/), { target: { value: '' } });
    const next = onChange.mock.calls.at(-1)![0] as SiteEntry[];
    expect(next[0].tx_power_dbm).toBeNull();
  });

  it('says which imported rows were rejected instead of dropping them', async () => {
    parseSitesCsv.mockResolvedValue({
      sites: [{ lat: 48, lon: 16, name: 'From CSV' }],
      count: 1,
      skipped: [{ line: 4, reason: 'lat/lon is not a number' }],
      columns: [],
    });
    const onChange = mount();
    const input = document.querySelector('input[type=file]') as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(['lat,lon\n48,16\n'], 's.csv', { type: 'text/csv' })] },
    });

    await waitFor(() => screen.getByText(/1 site\(s\) imported/i));
    // A planner who imports 40 sites and studies 38 must be told which two.
    expect(screen.getByText(/Row 4/)).toBeTruthy();
    expect(screen.getByText(/not a number/)).toBeTruthy();
    expect((onChange.mock.calls.at(-1)![0] as SiteEntry[]).at(-1)!.name)
      .toBe('From CSV');
  });

  it('surfaces an import failure rather than silently adding nothing', async () => {
    parseSitesCsv.mockRejectedValue(new Error("Site CSV needs at least 'lat' and 'lon'"));
    mount();
    const input = document.querySelector('input[type=file]') as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(['nope'], 's.csv', { type: 'text/csv' })] },
    });
    await waitFor(() => screen.getByRole('status'));
    expect(screen.getByRole('status').textContent).toMatch(/lat.*lon/i);
  });
});

describe('what actually reaches the API', () => {
  it('sends per-site overrides instead of dropping them on the wire', () => {
    // The regression: simulateMultiCoverage inlined four fields and dropped
    // the rest, so the UI could show an 800 MHz macro next to a 3.5 GHz
    // small cell and the backend still ran one preset across both.
    const body = siteBody({ lat: 47, lon: 15, name: 'Macro N',
                            antenna_azimuth_deg: 30, downtilt_deg: 3,
                            freq_mhz: 800, tx_power_dbm: 46 });
    expect(body.freq_mhz).toBe(800);
    expect(body.tx_power_dbm).toBe(46);
    expect(body.antenna_azimuth_deg).toBe(30);
  });

  it('omits a null override rather than sending null', () => {
    // `undefined` is what the API reads as "inherit"; an explicit null in a
    // field the caller never set is a different statement.
    const body = siteBody({ lat: 47, lon: 15, name: 'S', freq_mhz: null });
    expect('freq_mhz' in body).toBe(false);
  });
});
