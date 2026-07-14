/** Thin fetch wrappers for the terrain backend (proxied through /api). */
import type {
  AntennaInfo, CoverageResponse, GeorefRequest, GeorefResponse,
  IndoorCoverageResponse, Material, ModelInfo, ProfileResponse, Technology,
  TteResponse, TunnelResponse, UndergroundPresets, UploadResponse,
} from './types';

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

export async function simulateCoverage(params: {
  lat: number; lon: number; technology: string; radiusKm: number;
  dxfId: string | null;
  freqMhz?: number; model?: string | null; environment?: string | null;
  antennaAzimuthDeg?: number | null; antennaBeamwidthDeg?: number;
  antennaId?: string | null;
  downtiltDeg?: number; shadowMarginDb?: number;
  foliageDepthM?: number; rainRateMmH?: number;
  hBsM?: number;
  // Real site link-budget overrides (the preset is only a starting point):
  txPowerDbm?: number; txGainDbi?: number; rxGainDbi?: number;
  lossesDb?: number; rxSensitivityDbm?: number;
}): Promise<CoverageResponse> {
  return jsonOrThrow(await fetch('/api/rf/coverage', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
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
      h_bs_m: params.hBsM,
      tx_power_dbm: params.txPowerDbm,
      tx_gain_dbi: params.txGainDbi,
      rx_gain_dbi: params.rxGainDbi,
      losses_db: params.lossesDb,
      rx_sensitivity_dbm: params.rxSensitivityDbm,
    }),
  }));
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
  return `/api/terrain/profile.csv?${q.toString()}`;
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
    try { detail = (await resp.json()).detail ?? detail; } catch { /* keep */ }
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
      h_bs_m: params.hBsM,
      tx_power_dbm: params.txPowerDbm,
      rx_sensitivity_dbm: params.rxSensitivityDbm,
    }),
  }));
}
