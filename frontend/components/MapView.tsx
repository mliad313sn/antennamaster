'use client';

/**
 * Leaflet map: base OSM tiles, TX/RX markers, DXF footprint polygon and the
 * semi-transparent hillshade overlay of the georeferenced DXF terrain.
 *
 * This file is only ever loaded client-side (dynamic import with ssr:false
 * in page.tsx) because Leaflet touches `window` at module scope.
 */
import L from 'leaflet';
import { useEffect, useMemo } from 'react';
import {
  ImageOverlay, LayersControl, MapContainer, Marker, Polygon, Polyline, Popup,
  TileLayer, useMap, useMapEvents,
} from 'react-leaflet';
import type { CoverageResponse, GeorefResponse, LatLng } from '@/lib/types';

/**
 * Base-map providers.  Any XYZ tile service works — a custom URL template can
 * be supplied by the user (stored in localStorage) for private/WMTS-style
 * servers, so the app is not tied to a single map vendor.
 */
export const BASE_LAYERS: { name: string; url: string; attribution: string; maxZoom?: number }[] = [
  {
    name: 'OpenStreetMap',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  },
  {
    name: 'OpenTopoMap (relief)',
    url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
    attribution: '&copy; OpenStreetMap contributors, SRTM | © <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)',
    maxZoom: 17,
  },
  {
    name: 'Carto Light',
    url: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
    attribution: '&copy; OpenStreetMap contributors &copy; <a href="https://carto.com/">CARTO</a>',
  },
  {
    name: 'Carto Dark',
    url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    attribution: '&copy; OpenStreetMap contributors &copy; <a href="https://carto.com/">CARTO</a>',
  },
  {
    name: 'Esri World Imagery (satellite)',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Tiles &copy; Esri — Source: Esri, Maxar, Earthstar Geographics',
  },
  {
    name: 'Esri World Topo',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Tiles &copy; Esri — Source: Esri, HERE, Garmin, USGS',
  },
  {
    // Local tile server — serves pre-downloaded OSM tiles from the backend
    // cache; works with no internet. Pre-warm with tools/download_basemap.py.
    name: 'Offline cache (local)',
    url: '/api/basemap/{z}/{x}/{y}.png',
    attribution: '&copy; OpenStreetMap contributors — cached locally for offline use',
    maxZoom: 19,
  },
];

// Index of the local/offline base layer (last entry above).
const OFFLINE_LAYER_INDEX = BASE_LAYERS.length - 1;

// Leaflet's default marker images break under bundlers; use inline SVG pins.
function pin(color: string): L.DivIcon {
  return L.divIcon({
    className: '',
    iconSize: [28, 40],
    iconAnchor: [14, 38],
    html: `<svg width="28" height="40" viewBox="0 0 28 40" xmlns="http://www.w3.org/2000/svg">
      <path d="M14 0C6.3 0 0 6.3 0 14c0 10.5 14 26 14 26s14-15.5 14-26C28 6.3 21.7 0 14 0z"
            fill="${color}" stroke="#fff" stroke-width="1.5"/>
      <circle cx="14" cy="14" r="5" fill="#fff"/>
    </svg>`,
  });
}
const TX_ICON = pin('#2a78d6');
const RX_ICON = pin('#0b7a4b');

function ClickHandler({ onClick }: { onClick: (p: LatLng) => void }) {
  useMapEvents({ click: (e) => onClick({ lat: e.latlng.lat, lng: e.latlng.lng }) });
  return null;
}

/** Fly the map to the DXF footprint whenever a new georeferencing lands, so
 *  the user immediately sees where their drawing was placed. */
function FitToFootprint({ bounds }: { bounds: L.LatLngBounds | null }) {
  const map = useMap();
  useEffect(() => {
    if (bounds) map.fitBounds(bounds.pad(1.5), { maxZoom: 15 });
  }, [bounds, map]);
  return null;
}

export interface FlyTarget { lat: number; lng: number; zoom?: number; seq: number }

/** Imperative recenter used by the search box / GPS button. */
function FlyTo({ target }: { target: FlyTarget | null }) {
  const map = useMap();
  useEffect(() => {
    if (target) {
      map.flyTo([target.lat, target.lng],
        target.zoom ?? Math.max(map.getZoom(), 13));
    }
  }, [target, map]);
  return null;
}

/** Seamless offline fallback: when the browser loses connectivity, overlay
 *  the locally-cached base-map tiles (served by the backend tile server) on
 *  top of whatever provider is selected, so the map keeps rendering. The
 *  overlay is removed the moment connectivity returns, revealing the live
 *  tiles again. Pre-warm the cache with tools/download_basemap.py. */
function OfflineFallback() {
  const map = useMap();
  useEffect(() => {
    if (typeof L?.tileLayer !== 'function') return;   // guarded for tests
    let layer: ReturnType<typeof L.tileLayer> | null = null;
    const goOffline = () => {
      if (!layer) {
        layer = L.tileLayer('/api/basemap/{z}/{x}/{y}.png?offline=true', {
          maxZoom: 19, zIndex: 250,
          attribution: 'Cached OSM tiles (offline)',
        });
      }
      if (!map.hasLayer(layer)) layer.addTo(map);
    };
    const goOnline = () => { if (layer && map.hasLayer(layer)) map.removeLayer(layer); };
    const sync = () => (navigator.onLine ? goOnline() : goOffline());
    window.addEventListener('online', goOnline);
    window.addEventListener('offline', goOffline);
    sync();
    return () => {
      window.removeEventListener('online', goOnline);
      window.removeEventListener('offline', goOffline);
      if (layer && map.hasLayer(layer)) map.removeLayer(layer);
    };
  }, [map]);
  return null;
}

/** Remember the last map view so a reload reopens where the user worked. */
function ViewPersist() {
  useMapEvents({
    moveend: (e) => {
      const c = e.target.getCenter();
      try {
        localStorage.setItem('am_view',
          JSON.stringify({ lat: c.lat, lng: c.lng, z: e.target.getZoom() }));
      } catch { /* storage may be unavailable */ }
    },
  });
  return null;
}

function initialView(): { center: [number, number]; zoom: number } {
  try {
    const raw = localStorage.getItem('am_view');
    if (raw) {
      const v = JSON.parse(raw);
      if (Number.isFinite(v.lat) && Number.isFinite(v.lng)) {
        return { center: [v.lat, v.lng], zoom: v.z ?? 11 };
      }
    }
  } catch { /* fall through to default */ }
  return { center: [47.0, 15.0], zoom: 11 };
}

export interface MapViewProps {
  tx: LatLng | null;
  rx: LatLng | null;
  placing: 'tx' | 'rx' | null;
  onPlace: (p: LatLng) => void;
  georef: GeorefResponse | null;
  showOverlay: boolean;
  coverage: CoverageResponse | null;
  customTileUrl?: string;
  flyTarget?: FlyTarget | null;
}

export default function MapView({
  tx, rx, placing, onPlace, georef, showOverlay, coverage, customTileUrl,
  flyTarget,
}: MapViewProps) {
  const view = useMemo(initialView, []);
  const overlayBounds = useMemo(() => {
    if (!georef) return null;
    const [[s, w], [n, e]] = georef.overlay_bounds;
    return L.latLngBounds([s, w], [n, e]);
  }, [georef]);

  const coverageBounds = useMemo(() => {
    if (!coverage) return null;
    const [[s, w], [n, e]] = coverage.bounds;
    return L.latLngBounds([s, w], [n, e]);
  }, [coverage]);

  return (
    <>
      {placing && (
        <div className="map-hint">
          Click the map to place the {placing === 'tx' ? 'transmitter (TX)' : 'receiver (RX)'}
        </div>
      )}
      <MapContainer center={view.center} zoom={view.zoom} scrollWheelZoom>
        <LayersControl position="topright">
          {BASE_LAYERS.map((l, i) => (
            <LayersControl.BaseLayer key={l.name} name={l.name} checked={i === 0}>
              <TileLayer url={l.url} attribution={l.attribution}
                maxZoom={l.maxZoom ?? 19} />
            </LayersControl.BaseLayer>
          ))}
          {customTileUrl && (
            <LayersControl.BaseLayer name="Custom provider">
              <TileLayer url={customTileUrl} attribution="Custom tile provider" />
            </LayersControl.BaseLayer>
          )}
        </LayersControl>
        <ClickHandler onClick={onPlace} />
        <FitToFootprint bounds={overlayBounds} />
        <FlyTo target={flyTarget ?? null} />
        <ViewPersist />
        <OfflineFallback />

        {/* RF coverage raster (signal-strength classes; transparent = unserved). */}
        {coverage && coverageBounds && (
          <ImageOverlay
            url={coverage.png_url}
            bounds={coverageBounds}
            opacity={1 /* alpha baked into the PNG */}
            zIndex={380}
          />
        )}

        {/* Semi-transparent hillshade of the georeferenced DXF terrain. */}
        {georef && overlayBounds && showOverlay && (
          <ImageOverlay
            url={georef.overlay_url}
            bounds={overlayBounds}
            opacity={1 /* alpha is baked into the PNG */}
            zIndex={400}
          />
        )}

        {/* DXF footprint: the georeferenced bounding polygon (may be rotated).
            Non-interactive so TX/RX can be placed inside the DXF area — the
            grid details are shown in the sidebar instead of a popup. */}
        {georef && (
          <Polygon
            positions={georef.footprint}
            interactive={false}
            pathOptions={{ color: '#eb6834', weight: 2, dashArray: '6 4', fillOpacity: 0.04 }}
          />
        )}

        {tx && (
          <Marker position={[tx.lat, tx.lng]} icon={TX_ICON}>
            <Popup>TX — {tx.lat.toFixed(5)}, {tx.lng.toFixed(5)}</Popup>
          </Marker>
        )}
        {rx && (
          <Marker position={[rx.lat, rx.lng]} icon={RX_ICON}>
            <Popup>RX — {rx.lat.toFixed(5)}, {rx.lng.toFixed(5)}</Popup>
          </Marker>
        )}
        {tx && rx && (
          <Polyline
            positions={[[tx.lat, tx.lng], [rx.lat, rx.lng]]}
            pathOptions={{ color: '#0b0b0b', weight: 1.5, opacity: 0.65, dashArray: '2 6' }}
          />
        )}
      </MapContainer>
    </>
  );
}
