"""DXF floor-plan / gallery-layout extraction for indoor & underground studies.

Here a DXF is interpreted as *structure* (walls, pillars, gallery outlines)
rather than *relief*: LINE, LWPOLYLINE, POLYLINE and ARC entities on the
selected layers become 2D wall segments, each tagged with the material
assigned to its layer.  The multi-wall engine then counts TX->RX crossings
of these segments.

Coordinates stay in raw DXF drawing units; ``unit_scale`` (meters per unit)
converts distances for the physics.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from ezdxf.document import Drawing
from PIL import Image, ImageDraw

_ARC_SEG_DEG = 15.0  # arc tessellation step


@dataclass
class WallSet:
    """Wall segments grouped for vectorized intersection tests."""

    p0: np.ndarray        # (M, 2) segment start, DXF units
    p1: np.ndarray        # (M, 2) segment end
    material: list[str]   # per segment material key

    @property
    def count(self) -> int:
        return int(self.p0.shape[0])

    def bbox(self) -> tuple[float, float, float, float]:
        pts = np.vstack([self.p0, self.p1])
        x0, y0 = pts.min(axis=0)
        x1, y1 = pts.max(axis=0)
        return float(x0), float(y0), float(x1), float(y1)


def _entity_segments(entity) -> list[tuple[float, float, float, float]]:
    """2D segments (x0, y0, x1, y1) from one structural DXF entity."""
    kind = entity.dxftype()
    segs: list[tuple[float, float, float, float]] = []

    if kind == "LINE":
        s, e = entity.dxf.start, entity.dxf.end
        segs.append((s.x, s.y, e.x, e.y))

    elif kind == "LWPOLYLINE":
        pts = [(float(p[0]), float(p[1])) for p in entity.get_points()]
        closed = bool(entity.closed)
        for a, b in zip(pts, pts[1:] + ([pts[0]] if closed and len(pts) > 2 else [])):
            segs.append((a[0], a[1], b[0], b[1]))

    elif kind == "POLYLINE" and not (entity.is_poly_face_mesh or entity.is_polygon_mesh):
        pts = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices
               if not v.is_face_record]
        closed = bool(entity.is_closed)
        for a, b in zip(pts, pts[1:] + ([pts[0]] if closed and len(pts) > 2 else [])):
            segs.append((a[0], a[1], b[0], b[1]))

    elif kind in ("ARC", "CIRCLE"):
        c = entity.dxf.center
        r = float(entity.dxf.radius)
        if kind == "ARC":
            a0, a1 = float(entity.dxf.start_angle), float(entity.dxf.end_angle)
            if a1 <= a0:
                a1 += 360.0
        else:
            a0, a1 = 0.0, 360.0
        n = max(int((a1 - a0) / _ARC_SEG_DEG), 2)
        ang = np.radians(np.linspace(a0, a1, n + 1))
        xs, ys = c.x + r * np.cos(ang), c.y + r * np.sin(ang)
        for i in range(n):
            segs.append((float(xs[i]), float(ys[i]), float(xs[i + 1]), float(ys[i + 1])))

    return segs


def extract_walls(doc: Drawing, layer_materials: dict[str, str]) -> WallSet:
    """Wall segments from the layers named in ``layer_materials``
    (layer name -> material key).  Zero-length segments are dropped."""
    p0: list[tuple[float, float]] = []
    p1: list[tuple[float, float]] = []
    mats: list[str] = []
    for entity in doc.modelspace():
        material = layer_materials.get(entity.dxf.layer)
        if material is None or material == "none":
            continue
        for x0, y0, x1, y1 in _entity_segments(entity):
            if abs(x1 - x0) < 1e-9 and abs(y1 - y0) < 1e-9:
                continue
            p0.append((x0, y0))
            p1.append((x1, y1))
            mats.append(material)
    if not p0:
        return WallSet(np.empty((0, 2)), np.empty((0, 2)), [])
    return WallSet(np.asarray(p0, dtype=np.float64),
                   np.asarray(p1, dtype=np.float64), mats)


def render_preview(walls: WallSet, px: int = 900,
                   tx: tuple[float, float] | None = None) -> tuple[bytes, list[float]]:
    """Simple black-on-white plan rendering for TX placement in the UI.

    Returns (png_bytes, [x0, y0, x1, y1] DXF-unit bounds of the image) so the
    frontend can map image clicks back to DXF coordinates.
    """
    x0, y0, x1, y1 = walls.bbox() if walls.count else (0, 0, 1, 1)
    pad = 0.04 * max(x1 - x0, y1 - y0, 1.0)
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    w = x1 - x0
    h = y1 - y0
    if w >= h:
        img_w, img_h = px, max(int(px * h / w), 32)
    else:
        img_h, img_w = px, max(int(px * w / h), 32)

    img = Image.new("RGB", (img_w, img_h), (252, 252, 251))
    draw = ImageDraw.Draw(img)

    def to_px(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return ((x - x0) / w * (img_w - 1),
                (y1 - y) / h * (img_h - 1))          # y axis flips for image rows

    ax, ay = to_px(walls.p0[:, 0], walls.p0[:, 1])
    bx, by = to_px(walls.p1[:, 0], walls.p1[:, 1])
    for i in range(walls.count):
        draw.line([(ax[i], ay[i]), (bx[i], by[i])], fill=(30, 30, 30), width=2)
    if tx is not None:
        cx, cy = to_px(np.array([tx[0]]), np.array([tx[1]]))
        r = 6
        draw.ellipse([cx[0] - r, cy[0] - r, cx[0] + r, cy[0] + r],
                     fill=(42, 120, 214), outline=(255, 255, 255), width=2)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), [x0, y0, x1, y1]
