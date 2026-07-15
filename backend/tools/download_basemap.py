#!/usr/bin/env python3
"""Pre-download OpenStreetMap base-map tiles for a bounding box so the app
stays visually usable OFFLINE (remote/disconnected operational sites).

Usage:
    python -m tools.download_basemap \
        --bbox <south> <west> <north> <east> \
        --zoom 8-14 [--out <dir>] [--max 20000]

Example (an area around Graz, Austria, zoom 8..14):
    python -m tools.download_basemap --bbox 46.9 15.2 47.2 15.6 --zoom 8-14

Tiles are written to the same cache the local tile server reads
(AM_DATA_DIR/basemap_tiles by default), in the standard {z}/{x}/{y}.png
layout.  Please respect the OSM tile usage policy: pre-download modest areas,
not the planet.
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

import httpx

# Import the configured cache dir + source without pulling in the whole app.
try:
    from app.config import BASEMAP_CACHE_DIR, BASEMAP_URL
except Exception:  # run standalone from the backend/ dir
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.config import BASEMAP_CACHE_DIR, BASEMAP_URL

_UA = "AntennaMaster/2 (+offline basemap prefetch; RF coverage simulator)"


def deg2tile(lat: float, lon: float, z: int) -> tuple[int, int]:
    """Lat/lon → XYZ tile indices at zoom z (Web-Mercator)."""
    lat = max(min(lat, 85.05112878), -85.05112878)
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    lat_r = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def tile_range(south, west, north, east, z):
    x0, y0 = deg2tile(north, west, z)     # NW corner → min x, min y
    x1, y1 = deg2tile(south, east, z)     # SE corner → max x, max y
    return range(min(x0, x1), max(x0, x1) + 1), range(min(y0, y1), max(y0, y1) + 1)


def parse_zoom(s: str) -> range:
    if "-" in s:
        a, b = s.split("-", 1)
        return range(int(a), int(b) + 1)
    return range(int(s), int(s) + 1)


def main() -> int:
    ap = argparse.ArgumentParser(description="Pre-download OSM base-map tiles for offline use.")
    ap.add_argument("--bbox", nargs=4, type=float, required=True,
                    metavar=("SOUTH", "WEST", "NORTH", "EAST"))
    ap.add_argument("--zoom", default="8-14", help="single (12) or range (8-14)")
    ap.add_argument("--out", default=str(BASEMAP_CACHE_DIR),
                    help="output tile cache dir")
    ap.add_argument("--max", type=int, default=20000,
                    help="safety cap on the number of tiles")
    ap.add_argument("--delay", type=float, default=0.05,
                    help="seconds between requests (be polite to OSM)")
    args = ap.parse_args()

    south, west, north, east = args.bbox
    zooms = parse_zoom(args.zoom)
    out = Path(args.out)

    # Count first so the user can bail on an accidental continent.
    plan = []
    for z in zooms:
        xs, ys = tile_range(south, west, north, east, z)
        for x in xs:
            for y in ys:
                plan.append((z, x, y))
    total = len(plan)
    if total > args.max:
        print(f"Refusing: {total} tiles exceeds --max {args.max}. "
              f"Narrow the bbox or lower the max zoom.", file=sys.stderr)
        return 2
    print(f"Downloading {total} tiles (zoom {zooms.start}..{zooms.stop - 1}) "
          f"to {out}")

    client = httpx.Client(timeout=20.0, follow_redirects=True,
                          headers={"User-Agent": _UA})
    done = skipped = failed = 0
    for i, (z, x, y) in enumerate(plan, 1):
        path = out / str(z) / str(x) / f"{y}.png"
        if path.exists():
            skipped += 1
            continue
        try:
            r = client.get(BASEMAP_URL.format(z=z, x=x, y=y))
            r.raise_for_status()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            tmp.write_bytes(r.content)
            tmp.replace(path)
            done += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            if failed <= 5:
                print(f"  ! {z}/{x}/{y}: {exc}", file=sys.stderr)
        if i % 200 == 0 or i == total:
            print(f"  {i}/{total}  (new {done}, cached {skipped}, failed {failed})")
        time.sleep(args.delay)

    print(f"Done: {done} downloaded, {skipped} already cached, {failed} failed.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
