"""DXF terrain extraction with ezdxf.

Extracts (x, y, z) samples from the entity types that commonly carry relief
information in survey/CAD drawings:

* POINT            - direct 3D survey shots
* LWPOLYLINE       - 2D contour lines; Z comes from the `elevation` attribute
                     (a contour is one continuous entity at constant Z)
* POLYLINE         - 3D polylines, polygon meshes and POLYFACE meshes
* 3DFACE           - triangulated/quad TIN faces
* MESH             - subdivision mesh vertices
* TEXT / MTEXT     - spot heights: numeric labels placed at their true
                     position; the parsed number is used as Z at the insert point

All coordinates stay in raw DXF drawing units here; georeferencing happens in
`georef.py`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import ezdxf
import numpy as np
from ezdxf.document import Drawing

# Spot-height label like "123.4", "1,234.5" or "845", possibly with an
# elevation prefix ("EL 845.2", "H=845.2").
_SPOT_RE = re.compile(r"^\s*(?:EL\.?|ELEV\.?|H)?\s*[=:]?\s*(-?\d{1,5}(?:[.,]\d+)?)\s*m?\s*$",
                      re.IGNORECASE)

# Densification step (in drawing units) when sampling straight segments of
# contour polylines, so long contours contribute more than just vertices.
_DENSIFY_MAX_SEG = 0.0  # 0 disables densification; vertices are usually dense enough


@dataclass
class LayerInfo:
    name: str
    entity_count: int = 0
    point_count: int = 0
    z_min: float | None = None
    z_max: float | None = None
    entity_types: set[str] = field(default_factory=set)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "entity_count": self.entity_count,
            "point_count": self.point_count,
            "z_min": self.z_min,
            "z_max": self.z_max,
            "entity_types": sorted(self.entity_types),
            # Heuristic hint for the UI: layers with varying Z look like terrain.
            "looks_like_terrain": (
                self.point_count > 0
                and self.z_min is not None
                and self.z_max is not None
                and (self.z_max != 0 or self.z_min != 0)
            ),
        }


def _parse_spot_height(text: str) -> float | None:
    """Parse a TEXT/MTEXT string as a numeric spot height, or None."""
    m = _SPOT_RE.match(text.strip())
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _entity_points(entity) -> list[tuple[float, float, float]]:
    """Extract (x, y, z) samples from one DXF entity.  Unknown types -> []."""
    kind = entity.dxftype()
    pts: list[tuple[float, float, float]] = []

    if kind == "POINT":
        loc = entity.dxf.location
        pts.append((loc.x, loc.y, loc.z))

    elif kind == "LWPOLYLINE":
        # 2D polyline: constant Z stored in the `elevation` attribute
        # (standard for contour lines exported from GIS/CAD).
        z = float(entity.dxf.elevation)
        for x, y, *_ in entity.get_points():
            pts.append((float(x), float(y), z))

    elif kind == "POLYLINE":
        # Covers 2D/3D polylines, POLYFACE meshes and polygon meshes alike:
        # all of them expose their geometry through .vertices.
        if entity.is_poly_face_mesh or entity.is_polygon_mesh:
            for v in entity.vertices:
                # Skip the face-record pseudo-vertices of polyface meshes.
                if v.is_face_record:
                    continue
                loc = v.dxf.location
                pts.append((loc.x, loc.y, loc.z))
        else:
            const_z = float(entity.dxf.elevation.z) if entity.is_2d_polyline else None
            for v in entity.vertices:
                loc = v.dxf.location
                z = const_z if const_z is not None else loc.z
                pts.append((loc.x, loc.y, z))

    elif kind == "3DFACE":
        for attr in ("vtx0", "vtx1", "vtx2", "vtx3"):
            loc = getattr(entity.dxf, attr)
            pts.append((loc.x, loc.y, loc.z))

    elif kind == "MESH":
        for v in entity.vertices:
            pts.append((float(v[0]), float(v[1]), float(v[2])))

    elif kind in ("TEXT", "MTEXT"):
        raw = entity.dxf.text if kind == "TEXT" else entity.text
        z = _parse_spot_height(raw)
        if z is not None:
            loc = entity.dxf.insert
            pts.append((loc.x, loc.y, z))

    return pts


def list_layers(doc: Drawing) -> list[dict]:
    """Inventory every layer: entity/point counts, Z range, entity types.

    The frontend uses this to let the user pick which layers hold terrain.
    """
    layers: dict[str, LayerInfo] = {
        layer.dxf.name: LayerInfo(layer.dxf.name) for layer in doc.layers
    }
    for entity in doc.modelspace():
        lname = entity.dxf.layer
        info = layers.setdefault(lname, LayerInfo(lname))
        pts = _entity_points(entity)
        info.entity_count += 1
        info.entity_types.add(entity.dxftype())
        if pts:
            info.point_count += len(pts)
            zs = [p[2] for p in pts]
            lo, hi = min(zs), max(zs)
            info.z_min = lo if info.z_min is None else min(info.z_min, lo)
            info.z_max = hi if info.z_max is None else max(info.z_max, hi)
    return [info.as_dict() for info in layers.values()]


def extract_points(doc: Drawing, layer_names: list[str] | None = None) -> np.ndarray:
    """Scattered (N, 3) point cloud from the selected layers (raw DXF units).

    `layer_names=None` means "all layers".  Duplicate XY samples are removed
    (keeping the first) because scipy's Delaunay triangulation rejects them.
    """
    wanted = set(layer_names) if layer_names else None
    rows: list[tuple[float, float, float]] = []
    for entity in doc.modelspace():
        if wanted is not None and entity.dxf.layer not in wanted:
            continue
        rows.extend(_entity_points(entity))
    if not rows:
        return np.empty((0, 3), dtype=np.float64)
    arr = np.asarray(rows, dtype=np.float64)
    # De-duplicate identical XY locations to keep griddata happy.
    _, idx = np.unique(arr[:, :2].round(9), axis=0, return_index=True)
    return arr[np.sort(idx)]


def load_dxf(path: str) -> Drawing:
    """Open a DXF file, tolerating minor structural errors."""
    try:
        return ezdxf.readfile(path)
    except ezdxf.DXFStructureError:
        # Fall back to the recovery loader for slightly damaged files.
        from ezdxf import recover
        doc, _auditor = recover.readfile(path)
        return doc
