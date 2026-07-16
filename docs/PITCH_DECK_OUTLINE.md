# AntennaMaster — GTM Executive Pitch Deck (10 slides)

C-level narrative built on `docs/MARKET_BENCHMARK.md` (adversarially-verified
market research, 2026-07-16) and this repo's measured, CI-reproducible
numbers. Tone: clinical. Every figure on these slides has a source — either a
verified vendor publication or a test that runs in our CI.

---

## Slide 1 — The $50B blind spot
**Title:** *Radio planning runs the world's critical networks. Its tooling is
stuck in 2005.*
- Mines, ports, utilities, public safety, private 5G, WISPs — every one of
  them needs coverage predictions before steel goes up.
- The tools they must buy: contact-sales licensing (not one full-stack
  incumbent publishes a price), USB dongles, per-module add-ons, purchased
  geodata bundles, Windows-desktop workflows.
- The people who need answers most — the engineer in the pit, the integrator
  in the tunnel — are the furthest from the license server.
- **Speaker note:** every claim on the next 9 slides is either a vendor's own
  published document or a test the audience can run tonight.

## Slide 2 — Trust, but you can't verify
**Title:** *A precision market with no referee.*
- Verified finding: **no independent cross-tool accuracy benchmark exists.**
  Period. All accuracy figures are vendor self-published.
- The market's own numbers, verified as published: ATDI 2.56–2.99 dB SD
  (with a ±3 dB "Best mode" correlation that flatters it); iBwave 4–6 dB
  uncalibrated indoor, calibrated accuracy "out of scope" of its own white
  paper; Ranplan "≤6 dB RMS, independently verified" — verification details
  never published; Infovista Planet — **no accuracy figure at all**.
- Buyers sign six-figure contracts on adjectives.

## Slide 3 — The paradigm shift
**Title:** *AntennaMaster: Free. Complete. Exact.*
- Open-source, self-hosted RF planning platform: outdoor, indoor,
  underground, capacity, compliance — one codebase, 86 API endpoints,
  275 CI tests.
- Not "cheap Atoll" — a different epistemic contract: **every physics claim
  ships with an executable proof.**
- $0 per seat. No dongle. No geodata invoice. Runs air-gapped.

## Slide 4 — What "exact" means when we say it
**Title:** *0.0 dB — and CI blocks the release if it drifts.*
- **NTIA ITM (Longley-Rice):** reproduces the published Crystal Palace
  reference case at **0.0 dB deviation on all six confidence/reliability
  quantiles**; the CI gate fails any commit deviating > 0.1 dB.
- **ITU-R P.1812:** we run the **official ITU-R SG3 reference code** with the
  ITU digital maps — not a reimplementation.
- Same standards the incumbents list on their brochures (HTZ: P.1812-7, ITM;
  Atoll: model library) — none of them publishes a reproducible exactness
  proof. We are the only falsifiable vendor in the market.

## Slide 5 — The full stack, Layer 1 to Layer 5
**Title:** *From the physical layer to the boardroom.*
- **L1 Physics:** exact ITM + official P.1812 + P.530 availability + 38.901;
  ESA WorldCover 10 m clutter per pixel; drone LiDAR → DSM diffraction.
- **L2 Networks:** frequency/PCI planner (measured +3.3–5.4 dB SINR on test
  clusters), Erlang B/C, SINR→CQI throughput heatmaps, saturation verdicts.
- **L3 Indoor/underground:** visual DAS tree solver (exact per-antenna
  dB/EIRP), multi-floor stacks, leaky feeders with real datasheet curves,
  tunnels, through-the-earth.
- **L4 Operations:** 3D digital twin (Cesium), live telemetry with dead-zone
  correlation, offline PWA for the field.
- **L5 Business:** EMF dossiers, BOM/TCO, bilingual EN/FR PDF reporting.

## Slide 6 — Data honesty as a feature
**Title:** *194 devices. 143 verbatim from datasheets. 0 invented numbers.*
- Hardware catalog scraped from official vendor pages (MikroTik, Ubiquiti +
  curated OEMs) — every datasheet-grade record carries a machine-checkable
  `source_url`; CI enforces physical-sanity bounds and provenance.
- Drive-test calibration: CSV/GPX in → fit → **RMSE gates (8 dB urban / 6 dB
  rural) wired into CI**, proven end-to-end on labelled synthetic data.
- We print "field accuracy unproven until real campaigns are ingested" in our
  own benchmark. Ask the incumbents to print that sentence.

## Slide 7 — The moat, in one table
**Title:** *Where we stand, axis by axis.* (condensed Verdict Matrix)

| Axis | AntennaMaster | Best incumbent |
|---|---|---|
| Exactness proof | **0.0 dB, reproducible in CI** | None publishes one |
| Clutter data | WorldCover 10 m, free, automatic | Purchased bundles |
| Capacity | Erlang + throughput + freq/PCI, gain measured | Atoll (richer, national-scale) |
| Indoor/DAS | Exact DAS trees + multiwall, open catalog | iBwave/Ranplan (3D ray tracing) |
| Calibration | RMSE gates **in CI**, reproducible | Self-reported white papers |
| EMF compliance | Ready-to-file ICNIRP/FCC PDF | Only Ranplan confirmed |
| Price | **$0, open, air-gapped** | Contact-sales, dongles |

## Slide 8 — Where they still win (and why that helps us)
**Title:** *We concede three battles to win the war.*
- National-operator Monte Carlo & AFP/ACP at thousands of sites → Atoll/Planet
  keep the carrier HQ. **Not our buyer.**
- Deterministic 3D ray tracing & BIM/IFC ingestion → iBwave/Ranplan keep
  metal-heavy marquee venues. **10% of DAS jobs; we take the other 90%.**
- Sub-30 MHz / P.452 coordination → HTZ keeps the regulators. **Roadmap.**
- Saying this out loud is the credibility play the white-paper market can't
  make.

## Slide 9 — Deployment: the offline advantage
**Title:** *The only planner that works where the network doesn't.*
- One installer (Linux/macOS/Windows), self-bootstrapping; PWA + local
  basemap/DEM/WorldCover caches → **fully functional air-gapped**.
- Mining: plan leaky feeders and TTE links 800 m underground, no cloud.
- Public safety / defense: data-sovereign by construction — predictions,
  measurements and site data never leave the premises (HTZ sells this as a
  feature tier; we ship it as the default).
- Enterprise IT: no per-seat procurement cycle; the RF consultant's whole
  toolchain is a `git clone`.

## Slide 10 — ROI and the ask
**Title:** *The arithmetic and the plan.*
- **Cost displaced:** only public price in the market is Hamina at
  $980–1,560/user/yr for Wi-Fi-centric scope; full-stack incumbents are
  contact-sales (procurement folklore: tens of k$/seat/yr) + geodata + modules
  + training. AntennaMaster: $0 license, commodity hardware, open catalog.
- **Risk displaced:** falsifiable physics vs adjectives — the tender
  attachment is a CI log, not a brochure.
- **The ask:** (tailor per audience) pilot deployment in one mine /
  campus / county; contribute one real drive-test campaign to close the
  field-RMSE gates publicly; join the vendor-catalog program (your datasheets,
  verbatim, attributed).
- **Closing line:** *In a market with no referee, the falsifiable player
  sets the rules.*

---

*All competitor characterizations trace to `docs/MARKET_BENCHMARK.md`
(primary-source verified, 2026-07-16). All AntennaMaster numbers regenerate
from this repository's CI.*
