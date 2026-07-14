/** Shared API types mirroring the FastAPI backend schemas. */

export interface LayerInfo {
  name: string;
  entity_count: number;
  point_count: number;
  z_min: number | null;
  z_max: number | null;
  entity_types: string[];
  looks_like_terrain: boolean;
}

export interface UploadResponse {
  dxf_id: string;
  filename: string;
  layers: LayerInfo[];
}

export interface ControlPointPair {
  dxf_x: number;
  dxf_y: number;
  lat: number;
  lon: number;
}

export type GeorefMode = 'known_crs' | 'control_points' | 'origin_bearing';

export interface GeorefRequest {
  mode: GeorefMode;
  layers: string[] | null;
  crs?: string;
  control_points?: ControlPointPair[];
  origin_lat?: number;
  origin_lon?: number;
  bearing_deg?: number;
  unit_scale?: number;
  origin_x?: number;
  origin_y?: number;
  z_scale?: number;
}

export interface Validation {
  dxf_mean_m?: number;
  srtm_mean_m?: number;
  mean_diff_m?: number;
  threshold_m?: number;
  warning: string | null;
  error?: string;
}

export interface GeorefResponse {
  dxf_id: string;
  transform: Record<string, unknown> & {
    mode: GeorefMode;
    residuals_m?: number[];
    rms_residual_m?: number;
  };
  grid: { nx: number; ny: number; cell_size_m: number; points_used: number };
  footprint: [number, number][]; // [lat, lon] ring
  overlay_bounds: [[number, number], [number, number]]; // [[S,W],[N,E]]
  overlay_url: string;
  validation: Validation;
}

export type Provenance = 'srtm' | 'dxf' | 'blend';

export interface ProfilePoint {
  d: number;            // meters from TX
  lat: number;
  lon: number;
  elev: number;         // fused elevation (no curvature)
  elev_curved: number;  // with k=4/3 earth bulge - what RF math uses
  los: number;
  fresnel_lower: number;
  source: Provenance;
  dxf_weight: number;
  rx_power_dbm?: number; // present when a technology study is requested
}

/** Radio technology preset (GSM/UMTS/LTE/NR/PMR/broadcast/WLAN/IoT/PtP). */
export interface Technology {
  key: string;
  label: string;
  generation: string;
  freq_mhz: number;
  model: string;
  environment: string;
  tx_power_dbm: number;
  tx_gain_dbi: number;
  rx_gain_dbi: number;
  losses_db: number;
  rx_sensitivity_dbm: number;
  h_bs_m: number;
  h_ut_m: number;
}

export interface ModelInfo {
  key: string;
  label: string;
  f_range_mhz: [number, number];
  environments: string[];
  description: string;
}

export interface StudyResult {
  technology: Technology;
  path_loss_db: number;
  diffraction_loss_db: number;
  rx_power_dbm: number;
  margin_db: number;
  served: boolean;
  warnings: string[];
}

export interface CoverageResponse {
  coverage_id: string;
  png_url: string;
  bounds: [[number, number], [number, number]];
  legend: { margin_db: number; color: string; label: string }[];
  stats: {
    served_area_fraction: number;
    radius_m: number;
    tx_elevation_m: number;
    max_rx_power_dbm: number;
  };
  technology: Technology;
  warnings: string[];
}

export interface ProfileResponse {
  samples: number;
  dxf_id: string | null;
  distance_m: number;
  study: StudyResult | null;
  points: ProfilePoint[];
  rf: {
    line_of_sight_clear: boolean;
    fresnel_clearance_ratio: number;
    knife_edge_loss_db: number;
    worst_obstruction_index: number;
    worst_obstruction_v: number;
    k_factor: number;
    freq_mhz: number;
    tx_height_m: number;
    rx_height_m: number;
  };
}

export interface LatLng {
  lat: number;
  lng: number;
}
