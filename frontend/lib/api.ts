/** Thin fetch wrappers for the terrain backend (proxied through /api). */
import type {
  CoverageResponse, GeorefRequest, GeorefResponse, ModelInfo,
  ProfileResponse, Technology, UploadResponse,
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
  return jsonOrThrow(await fetch(`/api/terrain/profile?${q.toString()}`));
}

export async function fetchTechnologies(): Promise<Technology[]> {
  const body = await jsonOrThrow<{ technologies: Technology[] }>(
    await fetch('/api/rf/technologies'));
  return body.technologies;
}

export async function fetchModels(): Promise<ModelInfo[]> {
  const body = await jsonOrThrow<{ models: ModelInfo[] }>(await fetch('/api/rf/models'));
  return body.models;
}

export async function simulateCoverage(params: {
  lat: number; lon: number; technology: string; radiusKm: number;
  dxfId: string | null;
  freqMhz?: number; model?: string | null; environment?: string | null;
  antennaAzimuthDeg?: number | null; antennaBeamwidthDeg?: number;
  hBsM?: number;
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
      h_bs_m: params.hBsM,
    }),
  }));
}
