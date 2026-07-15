'use client';

/**
 * Globe3D — CesiumJS 3D digital-twin view.
 *
 * The 3D terrain is served by our OWN backend (`/api/terrain/heightmap`),
 * sampled from the fused SRTM+DXF model, via a CustomHeightmapTerrainProvider
 * — no Cesium Ion key, works offline. Cesium's global build is loaded at
 * runtime from `/cesium` (staged by scripts/copy-cesium.mjs) so it never
 * bloats the Next bundle, and heightmap decoding runs in Cesium's own Web
 * Workers so the UI thread never blocks.
 *
 * Renders: the TX/RX masts, a glowing semi-transparent 3D Fresnel cylinder
 * along the path, red markers where the 3D terrain slices into the Fresnel
 * zone, and (when present) the coverage heatmap draped over the terrain.
 */
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

type LatLng = { lat: number; lng: number };
type PPoint = { d: number; lat: number; lon: number; elev: number; los: number; fresnel_lower: number };
type Profile = { points: PPoint[] } | null;
type Coverage = { png_url: string; bounds: number[][] } | null;

declare global {
  interface Window { Cesium?: any; CESIUM_BASE_URL?: string }
}

let cesiumLoader: Promise<any> | null = null;
function loadCesium(): Promise<any> {
  if (typeof window === 'undefined') return Promise.reject(new Error('no window'));
  if (window.Cesium) return Promise.resolve(window.Cesium);
  if (cesiumLoader) return cesiumLoader;
  cesiumLoader = new Promise((resolve, reject) => {
    window.CESIUM_BASE_URL = '/cesium';
    const css = document.createElement('link');
    css.rel = 'stylesheet';
    css.href = '/cesium/Widgets/widgets.css';
    document.head.appendChild(css);
    const s = document.createElement('script');
    s.src = '/cesium/Cesium.js';
    s.async = true;
    s.onload = () => window.Cesium ? resolve(window.Cesium) : reject(new Error('Cesium global missing'));
    s.onerror = () => reject(new Error('Failed to load Cesium — run the build (copy-cesium)'));
    document.body.appendChild(s);
  });
  return cesiumLoader;
}

// First-Fresnel-zone radius (m) at a point d1 from TX, d2 from RX.
function fresnelRadius(d1: number, d2: number, freqMhz: number): number {
  const lam = 299.792458 / freqMhz; // wavelength in metres (c in Mm/s over MHz)
  const d = d1 + d2;
  if (d <= 0) return 0;
  return Math.sqrt((lam * d1 * d2) / d);
}

export default function Globe3D(
  { tx, rx, freqMhz, txHeight, rxHeight, profile, coverage, dxfId, onClose }: {
    tx: LatLng | null; rx: LatLng | null; freqMhz: number;
    txHeight: number; rxHeight: number; profile: Profile;
    coverage: Coverage; dxfId: string | null; onClose: () => void;
  },
) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let disposed = false;
    loadCesium().then((Cesium) => {
      if (disposed || !containerRef.current) return;
      try {
        Cesium.Ion.defaultAccessToken = ''; // never contact Ion
        const size = 65;
        const terrainProvider = new Cesium.CustomHeightmapTerrainProvider({
          width: size, height: size,
          tilingScheme: new Cesium.GeographicTilingScheme(),
          callback: async (x: number, y: number, level: number) => {
            if (level > 13) return undefined; // cap DEM fetch depth
            const q = dxfId ? `?size=${size}&dxf_id=${encodeURIComponent(dxfId)}` : `?size=${size}`;
            const r = await fetch(`/api/terrain/heightmap/${level}/${x}/${y}.bin${q}`);
            if (!r.ok) return undefined;
            const buf = await r.arrayBuffer();
            return Float32Array.from(new Int16Array(buf));
          },
        });
        const viewer = new Cesium.Viewer(containerRef.current, {
          terrainProvider,
          baseLayer: new Cesium.ImageryLayer(new Cesium.UrlTemplateImageryProvider({
            url: '/api/basemap/{z}/{x}/{y}.png', maximumLevel: 17,
          })),
          baseLayerPicker: false, geocoder: false, animation: false,
          timeline: false, sceneModePicker: false, navigationHelpButton: false,
          homeButton: false, fullscreenButton: false, infoBox: false,
          selectionIndicator: false,
        });
        viewer.scene.globe.depthTestAgainstTerrain = true;
        viewerRef.current = viewer;
        drawScene(Cesium, viewer);
        setReady(true);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    }).catch((e) => !disposed && setError(e.message));
    return () => {
      disposed = true;
      if (viewerRef.current && !viewerRef.current.isDestroyed()) {
        viewerRef.current.destroy();
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function drawScene(Cesium: any, viewer: any) {
    viewer.entities.removeAll();
    viewer.imageryLayers.length > 1 && viewer.imageryLayers.remove(viewer.imageryLayers.get(1));

    // Coverage heatmap draped over the 3D terrain.
    if (coverage?.png_url && coverage.bounds) {
      const [[s, w], [n, e]] = coverage.bounds;
      Cesium.SingleTileImageryProvider.fromUrl(coverage.png_url, {
        rectangle: Cesium.Rectangle.fromDegrees(w, s, e, n),
      }).then((p: any) => {
        const layer = viewer.imageryLayers.addImageryProvider(p);
        layer.alpha = 0.7;
      }).catch(() => { /* coverage optional */ });
    }

    if (!tx || !rx) {
      viewer.camera.flyTo({ destination: Cesium.Cartesian3.fromDegrees(0, 20, 12e6), duration: 0 });
      return;
    }

    const pts = profile?.points ?? [];
    const txElev = pts[0]?.elev ?? 0;
    const rxElev = pts[pts.length - 1]?.elev ?? 0;
    const txTop = txElev + txHeight;
    const rxTop = rxElev + rxHeight;

    // TX / RX masts.
    viewer.entities.add({
      name: 'TX',
      position: Cesium.Cartesian3.fromDegrees(tx.lng, tx.lat, txTop),
      point: { pixelSize: 12, color: Cesium.Color.CYAN, outlineColor: Cesium.Color.WHITE, outlineWidth: 2 },
      polyline: { positions: Cesium.Cartesian3.fromDegreesArrayHeights([tx.lng, tx.lat, txElev, tx.lng, tx.lat, txTop]), width: 3, material: Cesium.Color.CYAN },
    });
    viewer.entities.add({
      name: 'RX',
      position: Cesium.Cartesian3.fromDegrees(rx.lng, rx.lat, rxTop),
      point: { pixelSize: 12, color: Cesium.Color.ORANGE, outlineColor: Cesium.Color.WHITE, outlineWidth: 2 },
      polyline: { positions: Cesium.Cartesian3.fromDegreesArrayHeights([rx.lng, rx.lat, rxElev, rx.lng, rx.lat, rxTop]), width: 3, material: Cesium.Color.ORANGE },
    });

    // Line of sight.
    viewer.entities.add({
      name: 'LOS',
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArrayHeights([tx.lng, tx.lat, txTop, rx.lng, rx.lat, rxTop]),
        width: 2, material: new Cesium.PolylineGlowMaterialProperty({ glowPower: 0.25, color: Cesium.Color.LIME }),
      },
    });

    // 3D Fresnel cylinder (constant radius = the max first-Fresnel radius at
    // mid-path): a glowing, semi-transparent tube around the LOS.
    const total = pts.length ? pts[pts.length - 1].d
      : cartesianDistance(Cesium, tx, txTop, rx, rxTop);
    const rMax = fresnelRadius(total / 2, total / 2, freqMhz);
    const shape: any[] = [];
    for (let i = 0; i <= 32; i++) {
      const a = (i / 32) * 2 * Math.PI;
      shape.push(new Cesium.Cartesian2(rMax * Math.cos(a), rMax * Math.sin(a)));
    }
    // Follow the true LOS in 3D using the profile's per-sample LOS heights.
    const volPositions = pts.length
      ? Cesium.Cartesian3.fromDegreesArrayHeights(
          pts.flatMap((p) => [p.lon, p.lat, p.los]))
      : Cesium.Cartesian3.fromDegreesArrayHeights([tx.lng, tx.lat, txTop, rx.lng, rx.lat, rxTop]);
    viewer.entities.add({
      name: 'Fresnel',
      polylineVolume: {
        positions: volPositions, shape,
        material: Cesium.Color.CYAN.withAlpha(0.18),
        outline: true, outlineColor: Cesium.Color.CYAN.withAlpha(0.4),
      },
    });

    // Terrain intrusions: where the fused 3D terrain rises into the first
    // Fresnel zone (elevation >= the profile's Fresnel lower edge), mark red.
    for (let i = 1; i < pts.length - 1; i++) {
      const p = pts[i];
      if (p.elev >= p.fresnel_lower) {
        viewer.entities.add({
          position: Cesium.Cartesian3.fromDegrees(p.lon, p.lat, p.elev),
          point: { pixelSize: 7, color: Cesium.Color.RED.withAlpha(0.9) },
        });
      }
    }

    // Frame the link.
    viewer.flyTo(viewer.entities, { duration: 1.0 }).catch(() => {});
  }

  useEffect(() => {
    const Cesium = window.Cesium;
    if (ready && Cesium && viewerRef.current) drawScene(Cesium, viewerRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tx?.lat, tx?.lng, rx?.lat, rx?.lng, freqMhz, txHeight, rxHeight, coverage?.png_url, ready]);

  return (
    <div className="globe3d-wrap">
      <div className="globe3d-bar">
        <span>{t('globe.title')}</span>
        <button onClick={onClose}>{t('globe.exit')}</button>
      </div>
      {error && (
        <div className="globe3d-error">
          <b>{t('globe.unavailable')}</b>
          <p>{error}</p>
        </div>
      )}
      <div ref={containerRef} className="globe3d-canvas" />
    </div>
  );
}

function cartesianDistance(Cesium: any, a: LatLng, ah: number, b: LatLng, bh: number): number {
  const pa = Cesium.Cartesian3.fromDegrees(a.lng, a.lat, ah);
  const pb = Cesium.Cartesian3.fromDegrees(b.lng, b.lat, bh);
  return Cesium.Cartesian3.distance(pa, pb);
}
