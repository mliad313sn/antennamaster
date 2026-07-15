"""Distributed Antenna System (DAS) tree solver + combined indoor coverage.

An in-building DAS is a passive tree: a source (BDA / small cell) feeds coax
runs, splitters and tap couplers down to ceiling antennas. The design question
is "how much power actually reaches each antenna, and what does the combined
floor coverage look like?" — insertion loss tracked component by component.

Component nodes (JSON tree, ``children`` nests them):

  {"component": "cable",    "length_m": 30, "loss_db_per_100m": 11}
  {"component": "splitter", "ways": 2, "excess_db": 0.5}       # 10·log10(n)+excess
  {"component": "coupler",  "coupling_db": 10, "insertion_db": 0.5}
      children[0] = through port, children[1] = tap port
  {"component": "antenna",  "x": .., "y": .., "gain_dbi": 2}   # leaf

The solver walks the tree accumulating loss; every antenna leaf yields its
input power and EIRP. The coverage stage computes one multi-wall RX field per
antenna (same engine kernel as single-TX studies — identical physics) and
combines them element-wise (strongest server), rasterising one heatmap.
"""
from __future__ import annotations

import io
import math
import uuid

import numpy as np

from .engine import LEGEND_STEPS, IndoorResult, rx_power_field
from .floorplan import WallSet

MAX_ANTENNAS = 32
MAX_DEPTH = 24


class DasError(ValueError):
    """Invalid DAS tree."""


def solve_das(source_power_dbm: float, tree: dict) -> list[dict]:
    """Walk the tree; return the antennas with their delivered power/EIRP."""
    antennas: list[dict] = []

    def walk(node: dict, power: float, path: list[str], depth: int) -> None:
        if depth > MAX_DEPTH:
            raise DasError("DAS tree deeper than 24 components")
        if not isinstance(node, dict) or "component" not in node:
            raise DasError("every node needs a 'component' field")
        kind = node["component"]
        children = node.get("children", [])

        if kind == "antenna":
            if children:
                raise DasError("antenna must be a leaf")
            if len(antennas) >= MAX_ANTENNAS:
                raise DasError(f"more than {MAX_ANTENNAS} antennas")
            gain = float(node.get("gain_dbi", 0.0))
            antennas.append({
                "x": float(node["x"]), "y": float(node["y"]),
                "gain_dbi": gain,
                "input_power_dbm": round(power, 2),
                "eirp_dbm": round(power + gain, 2),
                "path": " → ".join(path + ["antenna"]),
            })
            return

        if kind == "cable":
            if len(children) != 1:
                raise DasError("cable must have exactly one child")
            loss = float(node["length_m"]) * float(node["loss_db_per_100m"]) / 100.0
            walk(children[0], power - loss,
                 path + [f"cable {node['length_m']:g}m (−{loss:.1f} dB)"],
                 depth + 1)
            return

        if kind == "splitter":
            ways = int(node.get("ways", len(children)))
            if ways < 2 or len(children) != ways:
                raise DasError("splitter needs ways>=2 and exactly that many children")
            loss = 10.0 * math.log10(ways) + float(node.get("excess_db", 0.5))
            for i, ch in enumerate(children):
                walk(ch, power - loss,
                     path + [f"split 1:{ways} (−{loss:.1f} dB)"], depth + 1)
            return

        if kind == "coupler":
            if len(children) != 2:
                raise DasError("coupler needs exactly 2 children (through, tap)")
            c = float(node["coupling_db"])
            if c <= 0:
                raise DasError("coupling_db must be positive")
            # Through-port loss: the power removed by the tap + excess.
            tap_frac = 10.0 ** (-c / 10.0)
            through = -10.0 * math.log10(max(1.0 - tap_frac, 1e-9)) \
                + float(node.get("insertion_db", 0.5))
            walk(children[0], power - through,
                 path + [f"coupler thru (−{through:.2f} dB)"], depth + 1)
            walk(children[1], power - c,
                 path + [f"coupler tap (−{c:g} dB)"], depth + 1)
            return

        raise DasError(f"unknown component {kind!r}")

    walk(tree, float(source_power_dbm), ["source"], 0)
    if not antennas:
        raise DasError("the DAS tree contains no antennas")
    return antennas


def das_coverage(walls: WallSet, antennas: list[dict], freq_mhz: float,
                 unit_scale: float = 1.0, rx_gain_dbi: float = 0.0,
                 rx_sensitivity_dbm: float = -82.0,
                 tx_height_m: float = 2.7, rx_height_m: float = 1.2,
                 grid_px: int = 200, raster_px: int = 900) -> IndoorResult:
    """Combined multi-antenna heatmap: per-antenna multi-wall fields (same
    kernel as single-TX studies) merged strongest-server."""
    combined = None
    bbox = None
    for a in antennas:
        field, bbox, _p1238 = rx_power_field(
            walls, a["x"], a["y"], freq_mhz, unit_scale=unit_scale,
            tx_power_dbm=a["input_power_dbm"], tx_gain_dbi=a["gain_dbi"],
            rx_gain_dbi=rx_gain_dbi, tx_height_m=tx_height_m,
            rx_height_m=rx_height_m, grid_px=grid_px)
        combined = field if combined is None else np.maximum(combined, field)

    margin = combined - rx_sensitivity_dbm
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0
    ny, nx = margin.shape

    # ---- raster (same visual language as the single-TX engine) -----------
    from PIL import Image, ImageDraw
    if w >= h:
        img_w, img_h = raster_px, max(int(raster_px * h / w), 32)
    else:
        img_h, img_w = raster_px, max(int(raster_px * w / h), 32)
    m_img = np.flipud(margin)
    yi = np.clip((np.arange(img_h) / max(img_h - 1, 1) * (ny - 1)).astype(int), 0, ny - 1)
    xi = np.clip((np.arange(img_w) / max(img_w - 1, 1) * (nx - 1)).astype(int), 0, nx - 1)
    m_big = m_img[yi][:, xi]
    rgba = np.zeros((img_h, img_w, 4), dtype=np.uint8)
    for thresh, color, _label in LEGEND_STEPS:
        mask = (m_big >= thresh) & (rgba[:, :, 3] == 0)
        rgba[mask, 0], rgba[mask, 1], rgba[mask, 2] = color
        rgba[mask, 3] = 175
    img = Image.fromarray(rgba, "RGBA")
    draw = ImageDraw.Draw(img)

    def to_px(xs, ys):
        return ((xs - x0) / w * (img_w - 1), (y1 - ys) / h * (img_h - 1))

    if walls.count:
        ax, ay = to_px(walls.p0[:, 0], walls.p0[:, 1])
        bx, by = to_px(walls.p1[:, 0], walls.p1[:, 1])
        for i in range(walls.count):
            draw.line([(ax[i], ay[i]), (bx[i], by[i])],
                      fill=(20, 20, 20, 255), width=2)
    for a in antennas:
        cx, cy = to_px(np.array([a["x"]]), np.array([a["y"]]))
        draw.ellipse([cx[0] - 6, cy[0] - 6, cx[0] + 6, cy[0] + 6],
                     fill=(18, 179, 166, 255), outline=(255, 255, 255, 255),
                     width=2)
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
            "antennas": len(antennas),
            "walls": walls.count,
            "max_rx_power_dbm": round(float(combined.max()), 1),
            "min_rx_power_dbm": round(float(combined.min()), 1),
        },
        warnings=[],
    )
