# Changelog

All notable changes to AntennaMaster are recorded here. Versions follow
[semantic versioning](https://semver.org/); the version shown is the app /
Windows-installer version (`dist/AntennaMaster-Setup-<version>.exe`).

## 1.1.0

### Added
- **Customizable sidebar (drag-and-drop).** An **Arrange panels** mode turns
  every planner sidebar tool into a draggable card: reorder panels by dragging
  the ⠿ handle (or focus it and use ↑ / ↓ — keyboard-accessible, WCAG 2.1.1),
  and hide the tools you never use. The layout (order + hidden set) persists
  per browser and is restored on every visit; **Reset** returns the default.
  Dependency-free native HTML5 drag-and-drop, so it works fully offline.
- **Guided-tour step** introducing the panel arranger, translated EN/FR.

### Changed
- **Coverage study colours.** The single-site and indoor area-coverage rasters
  now use a green → yellow → orange → red **traffic-light scale** (the
  Atoll / Radio-Mobile convention) instead of a single blue hue, so each of the
  five signal-margin levels reads as a distinct colour at a glance. The legend,
  GeoTIFF and KMZ exports pick up the new palette automatically.
- Terrain-validation warnings moved to the top of the sidebar (outside the
  reorderable set) so alerts stay prominent.

### Docs
- USER_GUIDE (EN/FR) and CAPABILITIES document the panel arranger and the
  updated coverage palette.

## 1.0.0

Initial release: terrain engine, DXF pipeline, six propagation models + ITM,
23 technology presets, single-site and multi-site best-server / SINR /
throughput coverage, indoor & underground studios, 3D digital twin, live
telemetry, drone LiDAR, bilingual (EN/FR) UI, Simple Mode, guided tour,
GIS exports (CSV / KML / KMZ / GeoTIFF), SaaS/accounts layer, and a
one-click Windows installer.
