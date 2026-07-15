#!/usr/bin/env python3
"""Generate the SYNTHETIC pipeline-proof drive-test datasets.

    python -m tools.make_sample_drive_test

Writes ``benchmarks/measurements/synthetic-{urban,rural}-pipelineproof.json``.

WHAT THESE ARE — AND ARE NOT.  Each dataset is the platform's own prediction
over the deterministic synthetic-ramp terrain plus seeded log-normal
shadowing of a realistic sigma (urban 6 dB, rural 4 dB).  Replaying them
end-to-end must yield RMSE ≈ sigma, which sits under the CI gates
(urban ≤ 8 dB, rural ≤ 6 dB) — proving the ingest → predict → fit → gate
machinery is correct and armed.  They are labelled ``"synthetic": true`` and
say so in their description: they are NOT field evidence, and the precision
report keeps stating that real-world RMSE remains unproven until real
campaign data is ingested via ``tools/ingest_drive_test.py``.
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.rf.planning import evaluate_receiver          # noqa: E402
from app.services.terrain.fusion import TerrainFusionService    # noqa: E402
from tools._ramp_terrain import RampTileStore                   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MEASUREMENTS = ROOT / "benchmarks" / "measurements"

TX = {"lat": 47.0, "lon": 15.0, "freq_mhz": 806.0,
      "tx_power_dbm": 43.0, "tx_gain_dbi": 12.0, "losses_db": 2.0,
      "h_m": 30.0}

CASES = [
    # (environment, shadowing sigma dB, CI gate dB, rng seed)
    ("urban", 6.0, 8.0, 1806),
    ("rural", 4.0, 6.0, 1806),
]


def ring_points(n_radials: int = 12, dists_m=(500, 1200, 2500, 4000, 6000)):
    for i in range(n_radials):
        az = 2 * math.pi * i / n_radials
        for d in dists_m:
            dlat = d * math.cos(az) / 111_320.0
            dlon = d * math.sin(az) / (111_320.0 * math.cos(math.radians(TX["lat"])))
            yield TX["lat"] + dlat, TX["lon"] + dlon


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        fusion = TerrainFusionService(store=RampTileStore(Path(tmp)))
        for env, sigma, gate, seed in CASES:
            tech = {"freq_mhz": TX["freq_mhz"], "model": "okumura_hata",
                    "environment": env, "tx_power_dbm": TX["tx_power_dbm"],
                    "tx_gain_dbi": TX["tx_gain_dbi"], "rx_gain_dbi": 0.0,
                    "losses_db": TX["losses_db"], "rx_sensitivity_dbm": -120.0,
                    "h_bs_m": TX["h_m"], "h_ut_m": 1.5}
            rng = np.random.default_rng(seed)
            points = []
            for lat, lon in ring_points():
                r = evaluate_receiver(fusion, dict(tech), TX["lat"], TX["lon"],
                                      lat, lon)
                rssi = r["rx_power_dbm"] + float(rng.normal(0.0, sigma))
                points.append({"lat": round(lat, 6), "lon": round(lon, 6),
                               "rssi_dbm": round(rssi, 1)})
            ds = {
                "name": f"synthetic-{env}-pipelineproof",
                "synthetic": True,
                "terrain": "ramp",
                "description": (
                    "SYNTHETIC pipeline-proof dataset — NOT field evidence. "
                    "Model prediction over the deterministic synthetic-ramp "
                    f"terrain + seeded log-normal shadowing (sigma {sigma:g} dB, "
                    f"seed {seed}). Proves the ingest->predict->fit->gate "
                    "pipeline end-to-end; replace with real campaigns via "
                    "tools/ingest_drive_test.py."),
                "environment": env,
                "model": "okumura_hata",
                "shadowing_sigma_db": sigma,
                "tx": TX,
                "rx_height_m": 1.5,
                "rmse_target_db": gate,
                "points": points,
            }
            out = MEASUREMENTS / f"{ds['name']}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(ds, indent=1) + "\n")
            print(f"wrote {out.name}: {len(points)} points, sigma={sigma} dB, "
                  f"gate={gate} dB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
