"""Indoor / underground coverage engine: COST-231 multi-wall over a DXF plan.

For every cell of a regular grid across the floor plan the engine computes

    L(cell) = FSPL_3D(d)  +  sum of material losses of every wall segment
              crossed by the straight TX->cell ray      (COST-231 multi-wall)

and derives RX power / margin from the study's link parameters.  Wall
crossings are found with a fully vectorized segment-segment intersection
test (one pass per wall over all grid cells), so a 200x200 grid against
hundreds of walls stays interactive.

Also provides the ITU-R P.1238 site-general indoor model (power-law +
floor penetration) for quick studies without a floor plan.
"""
from __future__ import annotations

import io
import uuid
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from .floorplan import WallSet
from .materials import material_loss_db

C_LIGHT = 299_792_458.0

# Margin-classed color ramp (same classes as the outdoor coverage engine).
LEGEND_STEPS = [
    (30.0, (13, 54, 107), "Excellent (≥ 30 dB margin)"),
    (20.0, (24, 79, 149), "Very good (≥ 20 dB)"),
    (12.0, (37, 106, 191), "Good (≥ 12 dB)"),
    (6.0, (85, 152, 231), "Fair (≥ 6 dB)"),
    (0.0, (158, 197, 244), "Marginal (≥ 0 dB)"),
]


def itu_p1238_loss_db(d_m: np.ndarray, freq_mhz: float,
                      n_floors: int = 0, environment: str = "office") -> np.ndarray:
    """ITU-R P.1238 site-general indoor path loss.

    L = 20 log10(f) + N log10(d) + Lf(n) - 28, with the distance power
    coefficient N and per-floor penetration Lf by environment class.
    """
    coeffs = {"residential": (28.0, 4.0 + 5.0 * (max(n_floors, 1) - 1)),
              "office": (30.0, 15.0 + 4.0 * (max(n_floors, 1) - 1)),
              "commercial": (22.0, 6.0 + 3.0 * (max(n_floors, 1) - 1))}
    n_coef, lf = coeffs.get(environment, coeffs["office"])
    d = np.maximum(np.asarray(d_m, dtype=np.float64), 1.0)
    loss = 20.0 * np.log10(freq_mhz) + n_coef * np.log10(d) - 28.0
    if n_floors > 0:
        loss += lf
    return loss


@dataclass
class IndoorResult:
    result_id: str
    png: bytes                      # coverage heatmap (walls composited on top)
    bounds_dxf: list[float]         # [x0, y0, x1, y1] drawing units
    legend: list[dict]
    stats: dict
    warnings: list[str] = field(default_factory=list)


def _fspl_db(d_m: np.ndarray, f_mhz: float) -> np.ndarray:
    return 32.44 + 20.0 * np.log10(np.maximum(d_m, 0.25) / 1000.0) + 20.0 * np.log10(f_mhz)


def simulate_indoor(walls: WallSet, tx_x: float, tx_y: float, freq_mhz: float,
                    unit_scale: float = 1.0,
                    tx_power_dbm: float = 20.0, tx_gain_dbi: float = 3.0,
                    rx_gain_dbi: float = 0.0, losses_db: float = 0.0,
                    rx_sensitivity_dbm: float = -82.0,
                    tx_height_m: float = 2.5, rx_height_m: float = 1.2,
                    grid_px: int = 200, raster_px: int = 900) -> IndoorResult:
    """Multi-wall coverage heatmap over the floor plan's bounding box."""
    warnings: list[str] = []
    x0, y0, x1, y1 = walls.bbox() if walls.count else (tx_x - 50, tx_y - 50,
                                                       tx_x + 50, tx_y + 50)
    pad = 0.04 * max(x1 - x0, y1 - y0, 1.0)
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad

    w, h = x1 - x0, y1 - y0
    if w >= h:
        nx, ny = grid_px, max(int(grid_px * h / w), 16)
    else:
        ny, nx = grid_px, max(int(grid_px * w / h), 16)
    gx = np.linspace(x0, x1, nx)
    gy = np.linspace(y0, y1, ny)
    mx, my = np.meshgrid(gx, gy)                      # (ny, nx), row 0 = south
    cells = np.column_stack([mx.ravel(), my.ravel()])  # (N, 2)

    # ---- wall-crossing losses: vectorized ray/segment intersection --------
    # Ray: TX -> cell (P + t*r, t in [0,1]); wall: A + u*s, u in [0,1].
    wall_loss = np.zeros(cells.shape[0])
    use_p1238 = walls.count == 0
    if walls.count:
        per_wall_loss = np.array([material_loss_db(m, freq_mhz)
                                  for m in walls.material])
        p = np.array([tx_x, tx_y])
        r = cells - p                                  # (N, 2)
        for i in range(walls.count):
            a = walls.p0[i]
            s = walls.p1[i] - a
            denom = r[:, 0] * s[1] - r[:, 1] * s[0]    # cross(r, s), (N,)
            ok = np.abs(denom) > 1e-12
            qp = a - p                                  # (2,)
            t = (qp[0] * s[1] - qp[1] * s[0]) / np.where(ok, denom, 1.0)
            u = (qp[0] * r[:, 1] - qp[1] * r[:, 0]) / np.where(ok, denom, 1.0)
            crossed = ok & (t > 0.0) & (t < 1.0) & (u >= 0.0) & (u <= 1.0)
            wall_loss += np.where(crossed, per_wall_loss[i], 0.0)
    else:
        warnings.append("No wall segments on the selected layers - falling "
                        "back to the ITU-R P.1238 site-general indoor model.")

    # ---- path loss + link budget ------------------------------------------
    d2d = np.hypot(cells[:, 0] - tx_x, cells[:, 1] - tx_y) * unit_scale
    d3d = np.sqrt(d2d ** 2 + (tx_height_m - rx_height_m) ** 2)
    if use_p1238:
        # No structural information: the statistical indoor model beats bare
        # FSPL, which would wildly overestimate in-building range.
        loss = itu_p1238_loss_db(d3d, freq_mhz, 0, "office")
    else:
        loss = _fspl_db(d3d, freq_mhz) + wall_loss
    rx = tx_power_dbm + tx_gain_dbi + rx_gain_dbi - losses_db - loss
    margin = (rx - rx_sensitivity_dbm).reshape(ny, nx)

    # ---- raster: heatmap + walls composited -------------------------------
    if w >= h:
        img_w, img_h = raster_px, max(int(raster_px * h / w), 32)
    else:
        img_h, img_w = raster_px, max(int(raster_px * w / h), 32)

    # Upsample margin to raster size (nearest is fine for classed colors);
    # note image row 0 = north = max y, while grid row 0 = south.
    m_img = np.flipud(margin)
    yi = np.clip((np.arange(img_h) / (img_h - 1) * (ny - 1)).astype(int), 0, ny - 1)
    xi = np.clip((np.arange(img_w) / (img_w - 1) * (nx - 1)).astype(int), 0, nx - 1)
    m_big = m_img[yi][:, xi]

    rgba = np.zeros((img_h, img_w, 4), dtype=np.uint8)
    for thresh, color, _label in LEGEND_STEPS:
        mask = (m_big >= thresh) & (rgba[:, :, 3] == 0)
        rgba[mask, 0], rgba[mask, 1], rgba[mask, 2] = color
        rgba[mask, 3] = 175
    img = Image.fromarray(rgba, "RGBA")

    # Composite the wall linework on top for orientation.
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)

    def to_px(xs: np.ndarray, ys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return ((xs - x0) / w * (img_w - 1), (y1 - ys) / h * (img_h - 1))

    if walls.count:
        ax, ay = to_px(walls.p0[:, 0], walls.p0[:, 1])
        bx, by = to_px(walls.p1[:, 0], walls.p1[:, 1])
        for i in range(walls.count):
            draw.line([(ax[i], ay[i]), (bx[i], by[i])], fill=(20, 20, 20, 255), width=2)
    cx, cy = to_px(np.array([tx_x]), np.array([tx_y]))
    draw.ellipse([cx[0] - 7, cy[0] - 7, cx[0] + 7, cy[0] + 7],
                 fill=(42, 120, 214, 255), outline=(255, 255, 255, 255), width=2)

    buf = io.BytesIO()
    img.save(buf, format="PNG")

    served = float(np.mean(margin >= 0.0))
    return IndoorResult(
        result_id=uuid.uuid4().hex[:12],
        png=buf.getvalue(),
        bounds_dxf=[x0, y0, x1, y1],
        legend=[{"margin_db": m, "color": "#%02x%02x%02x" % c, "label": l}
                for m, c, l in LEGEND_STEPS],
        stats={
            "served_area_fraction": round(served, 4),
            "walls": walls.count,
            "grid": [nx, ny],
            "max_rx_power_dbm": round(float(rx.max()), 1),
            "min_rx_power_dbm": round(float(rx.min()), 1),
        },
        warnings=warnings,
    )
