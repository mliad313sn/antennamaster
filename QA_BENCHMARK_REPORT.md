# QA_BENCHMARK_REPORT — Bounded Test/Benchmark/Refactor Cycle (×3)

Role: Principal QA Automation Engineer & DevOps Architect.
Protocol: 3 full iterations of (test-suite generation → benchmark → bounded
self-correction ≤3 loops → freeze). Core application code is now **frozen**.

## Test suites

| Suite | Framework | Count | Result |
|---|---|---|---|
| Backend unit + physics + API + security | pytest | **113 functions / 123 cases** | ✅ all pass (stable across repeated runs) |
| Frontend components | vitest + testing-library (jsdom) | **10** | ✅ all pass |
| Benchmark gates | `benchmarks/bench.py` (CI exit-code) | 8 scenarios | ✅ all pass |

**Backend line coverage: 90%** (2,650 statements, 263 uncovered — mostly
route error branches and the MSI/report layout long-tail).

Physics validated against known constants (already present + extended):
FSPL 1 km @1 GHz = 92.44 dB · Fresnel r₁ mid-10 km @1 GHz = 27.4 m ·
Okumura-Hata 5 km urban = 151.0 dB (hand-computed) · Terrarium decode,
skin depth 71.2 m @5 kHz/0.01 S/m · P.838 γ_R 2.75 dB/km @20 GHz/25 mm/h ·
earth bulge 36.8 m mid-50 km. Edge-case API tests: out-of-range lat/lon,
zero-length paths, antimeridian/polar paths, negative antenna gains (legal,
bounded), unknown ids, garbage DXF bytes, malformed bearer tokens — all
return clean 4xx, never 500.

## Benchmarks (offline synthetic DEM = pure compute; 2-pass: untraced wall
time + traced peak numpy memory; gates: ≤5 s, ≤1 GB)

| Scenario | Latency | Peak numpy mem |
|---|---|---|
| Profile 256 samples + per-sample Deygout study | **29 ms** | 0.2 MB |
| Profile 2,048 samples + study | **296 ms** | 2.5 MB |
| Coverage default 180×100 @10 km | **166 ms** | 21 MB |
| Coverage MAX 720×400 @50 km (SRTM) | **2.67 s** | 69 MB |
| Coverage MAX 720×400 @50 km + fused 400×400 DXF grid | **2.68 s** | 69 MB |
| Multi-site 4× (120×80 @10 km) + best-server composite | **366 ms** | 40 MB |
| Indoor multi-wall, 400 px grid, 200 walls | **660 ms** | 23 MB |
| Executive PDF (chart + tables) | **112 ms** | 2 MB |

## Iteration log

**Iteration 1** — added API edge-case suite, frontend harness (vitest),
benchmark harness. Gate failure: MAX coverage 6.7 s (>5 s).
Loop 1: fixed two frontend failures (ambiguous matcher; **real hardening
bug** — list-fetch wrappers crashed the UI on unexpected API shapes, now
`?? []`). Loop 2: chunked 3D broadcasting — no gain (workload is
memory-bandwidth-bound, not loop-overhead-bound). Loop 3: **float32
diffraction kernel** (halves memory traffic) + two-pass benchmark
methodology (tracemalloc adds 30–50% wall-time distortion): 6.7 s → 2.7 s
(2.4×), 128 MB → 69 MB. Also fixed a latent NameError + module-ordering bug
in the bench harness itself.

**Iteration 2** — gaps identified & closed: (1) no proof the float32
optimization preserves physics → added a **numerical-equivalence gate**
(engine vs unoptimized float64 triple-loop reference: max deviation
< 0.05 dB; plus a no-spurious-diffraction test on smooth terrain);
(2) PDF unbenchmarked → added (112 ms); (3) StudyPanel/IndoorStudio lacked
render tests → added. All suites green, zero correction loops needed.

**Iteration 3** — stability verification: back-to-back full runs of both
suites + benchmarks; identical pass results, latencies repeatable within
±10%. No fixes required. **Freeze declared.**

## Known limitations (documented, not quarantined — zero tests quarantined)

1. Benchmarks measure compute with a synthetic DEM; first-ever run over a
   new geography adds network tile-download time (measured ~25 s for a
   fresh 100×100 km area; ~0 s thereafter — disk cache).
2. Heavy sims run in the request thread-pool; sustained >10 concurrent
   max-resolution runs will queue (async job endpoint exists; a worker
   queue is the next scaling step).
3. pypdf-based PDF introspection unavailable in this environment (system
   `cryptography` conflict) — PDF assertions use structural checks
   (`%PDF-`, embedded `/Image`) + manual visual verification.
4. jsdom cannot execute real Leaflet/SVG layout; map tests exercise mount
   logic with stubbed react-leaflet (real-browser flows are covered by the
   Playwright scripts used throughout development).

## Launch the tested, production-ready application

```bash
./start.sh          # backend :8000 (uvicorn, 2 workers) + frontend :3000
```

CI-style full validation: `./start.sh --check` (backend tests + frontend
tests + benchmark gates; non-zero exit on any failure).
