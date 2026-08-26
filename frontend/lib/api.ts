/** Thin fetch wrappers for the terrain backend (proxied through /api). */
import type {
  BatchResponse, Equipment, OptimizeHeightsResponse, Scenario, ScenarioResolved, SiteCandidate,
  AntennaInfo, CoverageResponse, GeorefRequest, GeorefResponse,
  IndoorCoverageResponse, Material, ModelInfo, ProfileResponse, Technology,
  TteResponse, TunnelResponse, UndergroundPresets, UploadResponse,
} from './types';

/**
 * Turn a backend diagnostic into advice a planner can act on.
 *
 * The API speaks to API clients — it answers an overloaded worker with
 * "retry shortly or use POST /api/saas/coverage/async", which is useless
 * inside a GUI that has no address bar. Anything we don't recognise is passed
 * through untouched, so real errors are never masked.
 */
export function friendlyError(detail: string): string {
  if (/simulations already running|too many|busy/i.test(detail)) {
    return 'The server is busy with other simulations right now. '
      + 'Wait a moment and run the study again — nothing was lost.';
  }
  if (/timed out|timeout|gateway/i.test(detail)) {
    return 'The simulation took too long to answer. Try a smaller radius, or '
      + 'fewer radials/steps, and run it again.';
  }
  if (/failed to fetch|networkerror|load failed/i.test(detail)) {
    return 'Could not reach the simulation server. Check that it is running, '
      + 'then try again.';
  }
  return detail;
}

async function jsonOrThrow<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    } catch { /* keep statusText */ }
    throw new Error(detail);
  }
  return resp.json() as Promise<T>;
}

export async function uploadDxf(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append('file', file);
  return jsonOrThrow(await fetch('/api/dxf/upload', { method: 'POST', body: form }));
}

export async function georeference(
  dxfId: string, req: GeorefRequest,
): Promise<GeorefResponse> {
  return jsonOrThrow(await fetch(`/api/dxf/${dxfId}/georeference`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  }));
}

export async function fetchProfile(params: {
  lat1: number; lon1: number; lat2: number; lon2: number;
  dxfId: string | null;
  txHeight: number; rxHeight: number; freqMhz: number; samples?: number;
  technology?: string | null; model?: string | null; environment?: string | null;
  foliageDepthM?: number; rainRateMmH?: number;
  clutterPct?: number; surface?: boolean; clutterSource?: string;
}): Promise<ProfileResponse> {
  const q = new URLSearchParams({
    lat1: String(params.lat1), lon1: String(params.lon1),
    lat2: String(params.lat2), lon2: String(params.lon2),
    samples: String(params.samples ?? 256),
    tx_height_m: String(params.txHeight),
    rx_height_m: String(params.rxHeight),
  });
  // With a technology selected the preset frequency governs the study; the
  // manual frequency field only applies to plain terrain/Fresnel analysis.
  if (!params.technology) q.set('freq_mhz', String(params.freqMhz));
  if (params.dxfId) q.set('dxf_id', params.dxfId);
  if (params.technology) q.set('technology', params.technology);
  if (params.model) q.set('model', params.model);
  if (params.environment) q.set('environment', params.environment);
  if (params.foliageDepthM) q.set('foliage_depth_m', String(params.foliageDepthM));
  if (params.rainRateMmH) q.set('rain_rate_mm_h', String(params.rainRateMmH));
  if (params.clutterPct) q.set('clutter_pct', String(params.clutterPct));
  if (params.surface) q.set('surface', 'true');
  if (params.clutterSource) q.set('clutter_source', params.clutterSource);
  return jsonOrThrow(await fetch(`/api/terrain/profile?${q.toString()}`));
}

export async function fetchTechnologies(): Promise<Technology[]> {
  const body = await jsonOrThrow<{ technologies: Technology[] }>(
    await fetch('/api/rf/technologies'));
  return body.technologies ?? [];
}

export async function fetchModels(): Promise<ModelInfo[]> {
  const body = await jsonOrThrow<{ models: ModelInfo[] }>(await fetch('/api/rf/models'));
  return body.models ?? [];
}

export interface CoverageParams {
  lat: number; lon: number; technology: string; radiusKm: number;
  dxfId: string | null;
  freqMhz?: number; model?: string | null; environment?: string | null;
  antennaAzimuthDeg?: number | null; antennaBeamwidthDeg?: number;
  antennaId?: string | null;
  downtiltDeg?: number; shadowMarginDb?: number;
  foliageDepthM?: number; rainRateMmH?: number;
  clutterPct?: number; surface?: boolean; clutterSource?: string;
  hBsM?: number;
  // Drive-test calibration correction (apply-ready object from /calibrate):
  calibration?: object | null;
  // Real site link-budget overrides (the preset is only a starting point):
  txPowerDbm?: number; txGainDbi?: number; rxGainDbi?: number;
  lossesDb?: number; rxSensitivityDbm?: number;
}

export async function simulateCoverage(params: CoverageParams): Promise<CoverageResponse> {
  return jsonOrThrow(await fetch('/api/rf/coverage', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(coverageBody(params)),
  }));
}

/** Request body shared by the synchronous and the queued coverage paths, so
 *  the two can never drift apart. */
function coverageBody(params: CoverageParams): Record<string, unknown> {
  return {
      lat: params.lat, lon: params.lon,
      technology: params.technology, radius_km: params.radiusKm,
      dxf_id: params.dxfId ?? undefined,
      freq_mhz: params.freqMhz,
      model: params.model ?? undefined,
      environment: params.environment ?? undefined,
      antenna_azimuth_deg: params.antennaAzimuthDeg ?? undefined,
      antenna_beamwidth_deg: params.antennaBeamwidthDeg,
      antenna_id: params.antennaId ?? undefined,
      downtilt_deg: params.downtiltDeg,
      shadow_margin_db: params.shadowMarginDb,
      foliage_depth_m: params.foliageDepthM,
      rain_rate_mm_h: params.rainRateMmH,
      clutter_pct: params.clutterPct,
      surface: params.surface || undefined,
      clutter_source: params.clutterSource || undefined,
      h_bs_m: params.hBsM,
      calibration: params.calibration ?? undefined,
      tx_power_dbm: params.txPowerDbm,
      tx_gain_dbi: params.txGainDbi,
      rx_gain_dbi: params.rxGainDbi,
      losses_db: params.lossesDb,
      rx_sensitivity_dbm: params.rxSensitivityDbm,
  };
}

/**
 * Run a coverage study as a queued background job, reporting live progress.
 *
 * A full-resolution sweep (720 radials x 400 steps) takes ~26 s of pure
 * compute. Run synchronously that is a blocking request with no feedback,
 * at risk of a reverse-proxy gateway timeout, and it is refused with a 429
 * once six studies are already in flight on the worker. The queued path
 * instead reports progress the whole way and waits its turn under load, so
 * the UI stays honest and responsive at any resolution.
 *
 * `onProgress` receives 0..1. Falls back to the synchronous endpoint if the
 * job API is unavailable (e.g. an older backend), so the button always works.
 */
export async function simulateCoverageTracked(
  params: CoverageParams, onProgress: (fraction: number) => void,
  onStarted?: (cancel: () => void) => void,
): Promise<CoverageResponse> {
  const { startAsyncCoverage, awaitJob, cancelJob } = await import('./saas');
  let jobId: string;
  try {
    jobId = await startAsyncCoverage(coverageBody(params));
  } catch {
    return simulateCoverage(params);      // no job API - run it inline
  }
  // Hand the caller a way to stop it; a full-resolution sweep is ~26 s and a
  // run started with the wrong parameters should not have to be waited out.
  onStarted?.(() => { void cancelJob(jobId).catch(() => {}); });
  const job = await awaitJob(jobId, onProgress);
  if (job.status === 'cancelled') throw new CoverageCancelled();
  if (job.status === 'failed' || !job.result) {
    throw new Error(job.error || 'The coverage simulation failed.');
  }
  return job.result as unknown as CoverageResponse;
}

/** Thrown when the user stopped their own study — an expected outcome, so
 *  callers should clear the busy state without showing an error. */
export class CoverageCancelled extends Error {
  constructor() { super('Simulation cancelled'); this.name = 'CoverageCancelled'; }
}

export interface CoveragePoint {
  inside: boolean;
  distance_m: number;
  lat?: number; lon?: number;
  bearing_deg?: number;
  rx_power_dbm?: number;
  margin_db?: number;
  served?: boolean;
  grade?: { margin_db: number; color: string; label: string } | null;
}

/** Predicted level at one point of an existing coverage study — read out of
 *  the stored field, so it always agrees with the colour on the map. */
export async function coveragePointValue(
  coverageId: string, lat: number, lon: number,
): Promise<CoveragePoint> {
  return jsonOrThrow(await fetch(
    `/api/rf/coverage/${coverageId}/at?lat=${lat}&lon=${lon}`));
}

/** Restore a georeferenced DXF's map state (footprint/overlay) by id —
 *  used to rebuild the session after a page reload. */
export async function fetchDxfState(dxfId: string): Promise<GeorefResponse> {
  return jsonOrThrow(await fetch(`/api/dxf/${dxfId}/state`));
}

/** URL of the CSV export matching the given profile query (same params). */
export function profileCsvUrl(params: {
  lat1: number; lon1: number; lat2: number; lon2: number;
  dxfId: string | null; txHeight: number; rxHeight: number;
  freqMhz: number; technology?: string | null;
  model?: string | null; environment?: string | null;
  foliageDepthM?: number; rainRateMmH?: number;
  clutterPct?: number; surface?: boolean;
}): string {
  const q = new URLSearchParams({
    lat1: String(params.lat1), lon1: String(params.lon1),
    lat2: String(params.lat2), lon2: String(params.lon2),
    tx_height_m: String(params.txHeight), rx_height_m: String(params.rxHeight),
  });
  if (!params.technology) q.set('freq_mhz', String(params.freqMhz));
  if (params.dxfId) q.set('dxf_id', params.dxfId);
  if (params.technology) q.set('technology', params.technology);
  if (params.model) q.set('model', params.model);
  if (params.environment) q.set('environment', params.environment);
  if (params.foliageDepthM) q.set('foliage_depth_m', String(params.foliageDepthM));
  if (params.rainRateMmH) q.set('rain_rate_mm_h', String(params.rainRateMmH));
  if (params.clutterPct) q.set('clutter_pct', String(params.clutterPct));
  if (params.surface) q.set('surface', 'true');
  return `/api/terrain/profile.csv?${q.toString()}`;
}

/** URL of the KML/KMZ export of the current link (TX/RX + LoS + terrain)
 *  for Google Earth / GIS. */
export function profileKmlUrl(params: {
  lat1: number; lon1: number; lat2: number; lon2: number;
  dxfId: string | null; txHeight: number; rxHeight: number;
  freqMhz: number; surface?: boolean; kmz?: boolean;
}): string {
  const q = new URLSearchParams({
    lat1: String(params.lat1), lon1: String(params.lon1),
    lat2: String(params.lat2), lon2: String(params.lon2),
    tx_height_m: String(params.txHeight), rx_height_m: String(params.rxHeight),
    freq_mhz: String(params.freqMhz),
  });
  if (params.dxfId) q.set('dxf_id', params.dxfId);
  if (params.surface) q.set('surface', 'true');
  if (params.kmz) q.set('kmz', 'true');
  return `/api/terrain/profile.kml?${q.toString()}`;
}

// ------------------------------------------------ indoor / underground
export async function fetchMaterials(): Promise<Material[]> {
  const body = await jsonOrThrow<{ materials: Material[] }>(
    await fetch('/api/indoor/materials'));
  return body.materials ?? [];
}

export async function fetchUndergroundPresets(): Promise<UndergroundPresets> {
  return jsonOrThrow(await fetch('/api/indoor/presets'));
}

/** Floor-plan preview PNG + its DXF-unit bounds (from the response header). */
export async function fetchPlanPreview(
  dxfId: string, layers: string[],
): Promise<{ url: string; bounds: [number, number, number, number] }> {
  const resp = await fetch(
    `/api/indoor/${dxfId}/preview.png?layers=${encodeURIComponent(layers.join(','))}`);
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json()).detail ?? detail; } catch { /* non-JSON body */ }
    throw new Error(detail);
  }
  const bounds = (resp.headers.get('X-Plan-Bounds') ?? '0,0,1,1')
    .split(',').map(Number) as [number, number, number, number];
  const blob = await resp.blob();
  return { url: URL.createObjectURL(blob), bounds };
}

export async function simulateIndoorCoverage(params: {
  dxfId: string; layerMaterials: Record<string, string>;
  txX: number; txY: number; unitScale: number;
  technology?: string | null; freqMhz?: number;
  txPowerDbm?: number; rxSensitivityDbm?: number;
  floorsCrossed?: number; floorLossDb?: number;
}): Promise<IndoorCoverageResponse> {
  return jsonOrThrow(await fetch('/api/indoor/coverage', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      dxf_id: params.dxfId, layer_materials: params.layerMaterials,
      tx_x: params.txX, tx_y: params.txY, unit_scale: params.unitScale,
      technology: params.technology ?? undefined,
      freq_mhz: params.freqMhz, tx_power_dbm: params.txPowerDbm,
      rx_sensitivity_dbm: params.rxSensitivityDbm,
      floors_crossed: params.floorsCrossed,
      floor_loss_db: params.floorLossDb,
    }),
  }));
}

export async function fetchTunnelStudy(params: {
  freqMhz: number; widthM: number; heightM: number; lengthM: number;
  wall: string; txPowerDbm: number; txGainDbi: number; rxSensitivityDbm: number;
}): Promise<TunnelResponse> {
  const q = new URLSearchParams({
    freq_mhz: String(params.freqMhz), width_m: String(params.widthM),
    height_m: String(params.heightM), length_m: String(params.lengthM),
    wall: params.wall, tx_power_dbm: String(params.txPowerDbm),
    tx_gain_dbi: String(params.txGainDbi),
    rx_sensitivity_dbm: String(params.rxSensitivityDbm),
  });
  return jsonOrThrow(await fetch(`/api/indoor/tunnel?${q}`));
}

export async function fetchTteStudy(params: {
  freqHz: number; depthM: number; earth: string;
  txPowerDbm: number; rxSensitivityDbm: number;
}): Promise<TteResponse> {
  const q = new URLSearchParams({
    freq_hz: String(params.freqHz), depth_m: String(params.depthM),
    earth: params.earth, tx_power_dbm: String(params.txPowerDbm),
    rx_sensitivity_dbm: String(params.rxSensitivityDbm),
  });
  return jsonOrThrow(await fetch(`/api/indoor/tte?${q}`));
}

// ------------------------------------------------ antennas & multi-site
export async function uploadAntenna(file: File): Promise<AntennaInfo> {
  const form = new FormData();
  form.append('file', file);
  return jsonOrThrow(await fetch('/api/rf/antenna', { method: 'POST', body: form }));
}

export async function fetchAntennas(): Promise<AntennaInfo[]> {
  const body = await jsonOrThrow<{ antennas: AntennaInfo[] }>(
    await fetch('/api/rf/antennas'));
  return body.antennas ?? [];
}

export async function simulateMultiCoverage(params: {
  sites: { lat: number; lon: number; name?: string;
           antenna_azimuth_deg?: number | null; downtilt_deg?: number }[];
  technology: string; radiusKm: number; dxfId: string | null;
  antennaId?: string | null; model?: string | null; environment?: string | null;
  shadowMarginDb?: number; hBsM?: number;
  clutterPct?: number; surface?: boolean; clutterSource?: string;
  txPowerDbm?: number; rxSensitivityDbm?: number;
}): Promise<CoverageResponse> {
  return jsonOrThrow(await fetch('/api/rf/coverage/multi', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      sites: params.sites.map((s) => ({
        lat: s.lat, lon: s.lon, name: s.name,
        antenna_azimuth_deg: s.antenna_azimuth_deg ?? undefined,
        downtilt_deg: s.downtilt_deg ?? 0,
      })),
      technology: params.technology, radius_km: params.radiusKm,
      dxf_id: params.dxfId ?? undefined,
      antenna_id: params.antennaId ?? undefined,
      model: params.model ?? undefined,
      environment: params.environment ?? undefined,
      shadow_margin_db: params.shadowMarginDb,
      clutter_pct: params.clutterPct,
      surface: params.surface || undefined,
      clutter_source: params.clutterSource || undefined,
      h_bs_m: params.hBsM,
      tx_power_dbm: params.txPowerDbm,
      rx_sensitivity_dbm: params.rxSensitivityDbm,
    }),
  }));
}

/** Whether the backend has a surface model (DSM) tile source configured. */
export async function fetchSurfaceAvailable(): Promise<boolean> {
  try {
    const r = await fetch('/api/ready');
    const body = await r.json();
    return Boolean(body?.checks?.surface_model_configured);
  } catch {
    return false;
  }
}

// ------------------------------------------------- planning tools
export async function batchReceivers(params: {
  lat: number; lon: number; technology: string;
  receivers: { lat: number; lon: number; name?: string }[];
  dxfId?: string | null; kFactor?: number;
  foliageDepthM?: number; rainRateMmH?: number; clutterPct?: number;
  surface?: boolean; hBsM?: number;
}): Promise<BatchResponse> {
  return jsonOrThrow(await fetch('/api/rf/batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      lat: params.lat, lon: params.lon, technology: params.technology,
      receivers: params.receivers,
      dxf_id: params.dxfId ?? undefined,
      foliage_depth_m: params.foliageDepthM,
      rain_rate_mm_h: params.rainRateMmH,
      clutter_pct: params.clutterPct,
      surface: params.surface || undefined,
      h_bs_m: params.hBsM,
    }),
  }));
}

/** CSV download of a batch run (same body, format=csv). */
export async function batchReceiversCsv(body: object): Promise<Blob> {
  const r = await fetch('/api/rf/batch?format=csv', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.blob();
}

export async function optimizeHeights(params: {
  lat1: number; lon1: number; lat2: number; lon2: number;
  txHeight: number; rxHeight: number; freqMhz: number;
  technology?: string | null; dxfId?: string | null; surface?: boolean;
}): Promise<OptimizeHeightsResponse> {
  const q = new URLSearchParams({
    lat1: String(params.lat1), lon1: String(params.lon1),
    lat2: String(params.lat2), lon2: String(params.lon2),
    tx_height_m: String(params.txHeight),
    rx_height_m: String(params.rxHeight),
  });
  if (!params.technology) q.set('freq_mhz', String(params.freqMhz));
  if (params.technology) q.set('technology', params.technology);
  if (params.dxfId) q.set('dxf_id', params.dxfId);
  if (params.surface) q.set('surface', 'true');
  return jsonOrThrow(await fetch(`/api/terrain/optimize-heights?${q}`));
}

export async function searchBestSite(params: {
  south: number; west: number; north: number; east: number;
  technology: string; radiusKm: number; gridN?: number;
  clutterPct?: number; shadowMarginDb?: number;
  dxfId?: string | null; surface?: boolean; hBsM?: number;
}): Promise<{ candidates: SiteCandidate[] }> {
  return jsonOrThrow(await fetch('/api/rf/site-search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      south: params.south, west: params.west,
      north: params.north, east: params.east,
      technology: params.technology, radius_km: params.radiusKm,
      grid_n: params.gridN ?? 5,
      clutter_pct: params.clutterPct,
      shadow_margin_db: params.shadowMarginDb,
      dxf_id: params.dxfId ?? undefined,
      surface: params.surface || undefined,
      h_bs_m: params.hBsM,
    }),
  }));
}

// ------------------------------------------------- Simple Mode scenarios
export async function fetchScenarios(): Promise<Scenario[]> {
  const body = await jsonOrThrow<{ scenarios: Scenario[] }>(
    await fetch('/api/rf/scenarios'));
  return body.scenarios ?? [];
}

export async function resolveScenario(id: string): Promise<ScenarioResolved> {
  return jsonOrThrow(await fetch(`/api/rf/scenarios/${encodeURIComponent(id)}`));
}

// ------------------------------------------------- hardware catalog
export async function fetchEquipment(): Promise<{ equipment: Equipment[]; categories: string[] }> {
  const body = await jsonOrThrow<{ equipment: Equipment[]; categories: string[] }>(
    await fetch('/api/rf/equipment'));
  return { equipment: body.equipment ?? [], categories: body.categories ?? [] };
}

// ------------------------------------------------- advanced studies
async function postJson<T>(path: string, body: object): Promise<T> {
  return jsonOrThrow<T>(await fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }));
}

// Two-way LMR talk-back link.
export async function twowayLink(body: object): Promise<any> {
  return postJson('/api/rf/twoway/link', body);
}

// EMF exposure compliance (ICNIRP / FCC).
export async function emfCompliance(body: object): Promise<any> {
  return postJson('/api/rf/compliance', body);
}

// Longley-Rice ITM path loss with a reliability quantile.
export async function itmStudy(params: Record<string, string | number>): Promise<any> {
  const q = new URLSearchParams(
    Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)])));
  return jsonOrThrow(await fetch(`/api/terrain/itm?${q.toString()}`));
}

// Copilot engine-driven link diagnosis.
export async function copilotAnalyzeLink(body: object): Promise<any> {
  return postJson('/api/copilot/analyze/link', body);
}

function getWithParams(path: string, params: Record<string, string | number | boolean>) {
  const q = new URLSearchParams(
    Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)])));
  return fetch(`${path}?${q.toString()}`).then(jsonOrThrow) as Promise<any>;
}

// Official ITU-R P.1812 basic transmission loss (30 MHz - 6 GHz).
export async function p1812Study(params: Record<string, string | number | boolean>): Promise<any> {
  return getWithParams('/api/terrain/p1812', params);
}

// Official ITU-R P.452-18 clear-air interference loss (0.1 - 50 GHz).
export async function p452Study(params: Record<string, string | number | boolean>): Promise<any> {
  return getWithParams('/api/terrain/p452', params);
}

// Official ITU-R P.2001 wide-range model (30 MHz - 50 GHz, 0-100 % time).
export async function p2001Study(params: Record<string, string | number | boolean>): Promise<any> {
  return getWithParams('/api/terrain/p2001', params);
}

// ITU-R P.530 annual availability of a PtP hop.
export async function availabilityStudy(params: Record<string, string | number | boolean>): Promise<any> {
  return getWithParams('/api/terrain/availability', params);
}

// Automatic frequency / PCI plan over a site cluster.
export async function frequencyPlan(body: object): Promise<any> {
  return postJson('/api/rf/frequency-plan', body);
}

// Erlang B/C trunking dimensioning.
export async function erlangStudy(params: Record<string, string | number | boolean>): Promise<any> {
  return getWithParams('/api/rf/erlang', params);
}

// Per-cell capacity + Mbit/s heatmap from the SINR field (3GPP CQI ladder).
export async function throughputMap(body: object): Promise<any> {
  return postJson('/api/rf/throughput-map', body);
}

// Drive-test calibration: fit offset/slope from measured RSSI points.
export async function calibrateDriveTest(body: object): Promise<any> {
  return postJson('/api/rf/calibrate', body);
}

// Monte Carlo traffic snapshots over a site cluster.
export async function monteCarloTraffic(body: object): Promise<any> {
  return postJson('/api/rf/montecarlo', body);
}

// DAS tree solver: splitters/couplers/cables -> per-antenna EIRP.
export async function dasSolve(body: object): Promise<any> {
  return postJson('/api/indoor/das', body);
}

// Stacked multi-floor indoor study (per-floor walls + slab losses).
export async function indoorStack(body: object): Promise<any> {
  return postJson('/api/indoor/stack', body);
}

// Ready-to-file EMF dossier (PDF blob).
export async function emfReportPdf(body: object): Promise<Blob> {
  const r = await fetch('/api/rf/compliance/report.pdf', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.blob();
}

// Leaky-feeder (radiating cable) tunnel study.
export async function leakyFeederStudy(body: object): Promise<any> {
  return postJson('/api/indoor/leaky-feeder', body);
}

// Drone LiDAR / point-cloud DSM upload.
export async function uploadLidar(file: File, epsg?: string, cellM = 2): Promise<any> {
  const form = new FormData();
  form.append('file', file);
  if (epsg) form.append('epsg', epsg);
  form.append('cell_m', String(cellM));
  return jsonOrThrow(await fetch('/api/lidar/upload', { method: 'POST', body: form }));
}

// Profile whose diffraction is computed against the surveyed 3D surface.
export async function lidarProfile(dsmId: string, params: Record<string, string | number>): Promise<any> {
  const q = new URLSearchParams(
    Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)])));
  return jsonOrThrow(await fetch(`/api/lidar/${dsmId}/profile?${q.toString()}`));
}
