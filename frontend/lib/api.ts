/** Thin fetch wrappers for the terrain backend (proxied through /api). */
import type {
  GeorefRequest, GeorefResponse, ProfileResponse, UploadResponse,
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
}): Promise<ProfileResponse> {
  const q = new URLSearchParams({
    lat1: String(params.lat1), lon1: String(params.lon1),
    lat2: String(params.lat2), lon2: String(params.lon2),
    samples: String(params.samples ?? 256),
    tx_height_m: String(params.txHeight),
    rx_height_m: String(params.rxHeight),
    freq_mhz: String(params.freqMhz),
  });
  if (params.dxfId) q.set('dxf_id', params.dxfId);
  return jsonOrThrow(await fetch(`/api/terrain/profile?${q.toString()}`));
}
