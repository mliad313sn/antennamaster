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
  ImageOverlay, MapContainer, Marker, Polygon, Polyline, Popup, TileLayer,
  useMap, useMapEvents,
} from 'react-leaflet';
import type { GeorefResponse, LatLng } from '@/lib/types';

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

export interface MapViewProps {
  tx: LatLng | null;
  rx: LatLng | null;
  placing: 'tx' | 'rx' | null;
  onPlace: (p: LatLng) => void;
  georef: GeorefResponse | null;
  showOverlay: boolean;
}

export default function MapView({ tx, rx, placing, onPlace, georef, showOverlay }: MapViewProps) {
  const overlayBounds = useMemo(() => {
    if (!georef) return null;
    const [[s, w], [n, e]] = georef.overlay_bounds;
    return L.latLngBounds([s, w], [n, e]);
  }, [georef]);

  return (
    <>
      {placing && (
        <div className="map-hint">
          Click the map to place the {placing === 'tx' ? 'transmitter (TX)' : 'receiver (RX)'}
        </div>
      )}
      <MapContainer center={[47.0, 15.0]} zoom={11} scrollWheelZoom>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <ClickHandler onClick={onPlace} />
        <FitToFootprint bounds={overlayBounds} />

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
