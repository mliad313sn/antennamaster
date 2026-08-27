"""Automated benchmark harness for the RF engines.

Runs offline (synthetic DEM world) so numbers measure COMPUTE, not network.
Gates: every scenario must return within its budget (default 5 s) and peak
numpy allocations must stay under the memory bound.

Usage:  python -m benchmarks.bench          (from backend/)
Exit code 1 if any gate fails - CI-friendly.
"""
from __future__ import annotations

import json
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from tests.conftest import FakeTileStore  # noqa: E402  (synthetic DEM world)

TIME_GATE_S = 5.0
MEM_GATE_MB = 1024.0


def _store(tmp: Path) -> FakeTileStore:
    return FakeTileStore(tmp)


def bench(name: str, fn, budget_s: float = TIME_GATE_S) -> dict:
    """Two-pass measurement: wall time on an untraced run (tracemalloc adds
    30-50% overhead to allocation-heavy numpy code, which would gate on
    instrumentation, not the product), then a traced run for peak memory."""
    t0 = time.perf_counter()
    fn()
    elapsed = time.perf_counter() - t0

    tracemalloc.start()
    fn()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mb = peak / 1024 / 1024
    ok = elapsed <= budget_s and peak_mb <= MEM_GATE_MB
    print(f"{'PASS' if ok else 'FAIL':4} {name:52} {elapsed*1000:8.0f} ms "
          f"peak {peak_mb:7.1f} MB")
    return {"name": name, "ms": round(elapsed * 1000), "peak_mb": round(peak_mb, 1),
            "ok": ok, "budget_s": budget_s}


def main() -> int:
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    store = _store(tmp)

    from app.services.dxf.georef import OriginBearingTransform
    from app.services.dxf.gridder import build_grid
    from app.services.rf.technologies import get_technology
    from app.services.terrain.coverage import CoverageEngine, composite_best_server
    from app.services.terrain.fusion import TerrainFusionService

    fusion = TerrainFusionService(store=store)
    engine = CoverageEngine(fusion)
    tech = get_technology("gsm900")

    # Max-resolution fused DXF grid (400x400) over a 12x12 km site.
    georef = OriginBearingTransform(origin_lat=47.0, origin_lon=15.0)
    n = 120
    xs = np.linspace(0, 12_000, n)
    mx, my = np.meshgrid(xs, xs)
    z = 350 + 40 * np.sin(mx / 800) * np.cos(my / 600)
    pts = np.column_stack([mx.ravel(), my.ravel(), z.ravel()])
    grid = build_grid(pts, target_cells=400)

    results = [
        bench("profile 256 samples + study (Deygout per-sample)",
              lambda: __import__("app.services.terrain.fusion", fromlist=["x"]) and
              _profile(fusion, 256)),
        bench("profile 2048 samples + study",
              lambda: _profile(fusion, 2048)),
        bench("coverage default 180x100 @10km",
              lambda: engine.simulate(47.0, 15.0, dict(tech),
                                      radius_m=10_000, n_radials=180, n_steps=100)),
        bench("coverage MAX 720x400 @50km (SRTM)",
              lambda: engine.simulate(47.0, 15.0, dict(tech),
                                      radius_m=50_000, n_radials=720, n_steps=400)),
        bench("coverage MAX 720x400 @50km FUSED DXF grid",
              lambda: engine.simulate(47.05, 15.05, dict(tech),
                                      radius_m=50_000, n_radials=720, n_steps=400,
                                      grid=grid, georef=georef)),
        # ITM runs the full Longley-Rice algorithm once per sample instead of
        # evaluating a curve, so its cost scales with the sample count in a
        # way none of the empirical models do. Gate it: an engine that
        # quietly became ten times slower would turn the default study from
        # interactive into abandoned.
        bench("coverage ITM 180x100 @10km (one Longley-Rice run per sample)",
              lambda: engine.simulate(47.0, 15.0, dict(tech, model="itm"),
                                      radius_m=10_000, n_radials=180,
                                      n_steps=100)),
        bench("multi-site 4x (120x80 @10km) + composite",
              lambda: _multi(engine, tech)),
        bench("indoor multi-wall 400px grid, 200 walls",
              lambda: _indoor()),
        bench("executive PDF (profile chart + tables)",
              lambda: _pdf(fusion)),
    ]

    out = Path(__file__).parent / "results.json"
    out.write_text(json.dumps(results, indent=1))
    print(f"\nresults -> {out}")
    return 0 if all(r["ok"] for r in results) else 1


def _profile(fusion, samples: int) -> None:
    from app.services.rf.models import deygout_loss_db, path_loss_db
    from app.services.rf.physics import apply_earth_curvature
    prof = fusion.profile(47.0, 14.6, 47.0, 15.4, n_samples=samples)
    curved = apply_earth_curvature(prof.distances_m, prof.elevations_m)
    path_loss_db("okumura_hata", np.maximum(prof.distances_m, 1.0), 900, 30, 1.5)
    for i in range(2, len(prof.distances_m)):
        deygout_loss_db(prof.distances_m[:i + 1], curved[:i + 1], 30, 1.5, 900)


def _multi(engine, tech) -> None:
    from app.services.terrain.coverage import composite_best_server
    sites = []
    for i, (la, lo) in enumerate([(47.0, 15.0), (47.05, 15.1),
                                  (46.95, 15.05), (47.02, 14.9)]):
        polar = engine.compute_polar(la, lo, dict(tech), radius_m=10_000,
                                     n_radials=120, n_steps=80)
        sites.append({"lat": la, "lon": lo, "name": f"S{i}",
                      "radius_m": 10_000.0, "polar": polar})
    composite_best_server(sites)


def _indoor() -> None:
    from app.services.indoor.engine import simulate_indoor
    from app.services.indoor.floorplan import WallSet
    rng = np.random.default_rng(7)
    p0 = rng.uniform(0, 200, (200, 2))
    p1 = p0 + rng.uniform(-30, 30, (200, 2))
    walls = WallSet(p0, p1, ["concrete"] * 200)
    simulate_indoor(walls, 100, 100, 2442.0, grid_px=400, raster_px=600)




def _pdf(fusion) -> None:
    from app.services.saas.costs import estimate
    from app.services.saas.report import build_report
    prof = fusion.profile(47.0, 14.8, 47.0, 15.2, n_samples=256)
    points = [{"d": float(d), "elev_curved": float(e), "los": float(e) + 40,
               "dxf_weight": 0.0}
              for d, e in zip(prof.distances_m, prof.elevations_m)]
    build_report(title="Bench", org_name="Bench Org", logo_png=None,
                 study=None, profile_points=points,
                 rf={"line_of_sight_clear": True, "knife_edge_loss_db": 0,
                     "fresnel_clearance_ratio": 1.2, "k_factor": 4 / 3},
                 distance_m=30_000.0, coverage_png=None, coverage_stats=None,
                 costs=estimate("private_nr_n77", 3))


if __name__ == "__main__":
    sys.exit(main())
