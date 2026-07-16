# AntennaMaster — Market Benchmark

**Scope.** AntennaMaster (this repository, measured directly from code, CI and
live endpoints) versus the commercial RF-planning market, established by an
adversarially-verified research pass run on 2026-07-16: 106 research agents,
every competitor claim fetched from primary vendor sources and subjected to
3-voter adversarial verification (≥2/3 refutations kill a claim). Fourteen
findings survived, covering the six closest competitors: **Forsk Atoll,
ATDI HTZ Communications, Infovista Planet, iBwave Design, Ranplan
Professional, Hamina Network Planner**. Claims about tools that did not
survive verification (Pathloss, CloudRF, SPLAT!, Radio Mobile, EDX, TAP,
Ekahau, Siradel, Remcom) are marked as such and used only qualitatively.

**Method note (read before quoting).** Every AntennaMaster number in this
document is *measured*: reproducible from this repo's CI (`pytest`,
`tools/validate_predictions.py`) or a live endpoint. Every competitor number
is *vendor self-reported*, verified only as "the vendor really publishes
this" — because, as the research itself established, **no independent
head-to-head benchmark of these tools exists publicly**. That asymmetry is
the market gap this document exploits.

---

## 1. The Verdict Matrix

AntennaMaster vs the five closest full-stack competitors, seven axes.

| Axis | **AntennaMaster** (measured) | Forsk Atoll | ATDI HTZ | Infovista Planet | iBwave Design | Ranplan Professional |
|---|---|---|---|---|---|---|
| **Physics exactness** | NTIA ITM (itmlogic) reproduces the published Crystal Palace reference at **0.0 dB on all 6 quantiles**, CI-gated ≤ 0.1 dB; **ITU-R P.1812 official SG3 reference code** + ITU digital maps; P.530-class availability; 38.901 UMa/UMi/RMa; Hata/COST-231; proof regenerated in CI, public | Integrated model library + optional Aster ray tracing + CrossWave; no public exactness proof | **Broadest library: 50+ models** (P.1812-7, P.452-18, P.530-18, P.1546-6, NTIA ITM, M.2412/38.901-class, kHz–1 THz); no public exactness proof | Ray-launching 3D + AI model (AIM) + Google propagation API; ITU-R/ITM not even named on product page; **no quantified accuracy figures published** | Indoor Fast Ray Tracing (+ VPLE, COST-231 MW) | 3D ray-tracing/launching, vendor claims ≤ 6 dB RMS (details of "independent verification" unpublished) |
| **Clutter / terrain data** | **ESA WorldCover 10 m auto-fetched per pixel** (P.1812 representative heights), building-footprint DSM rasterization, **drone LiDAR .las/.laz → DSM**, SRTM + surveyed DXF fusion — all free sources, zero licensing | DEM/clutter/3D buildings/traffic ingestion, MapInfo/ArcGIS/WMS — geodata typically **purchased** | SRTM, LiDAR, OS, Corine, OSM via ATDI-supplied bundles (tied to maintenance contract) | High-res 3D building & vegetation vectors (commercial geodata) | Indoor: manual walls/materials, no geo clutter | BIM/IFC import, AutoCAD 2D→3D reconstruction, 3D mesh |
| **Capacity modeling** | Erlang B/C (anchored to published tables in CI), SINR→CQI throughput maps + per-cell saturation verdicts, **frequency/PCI planner with the SINR gain measured on the same grid** (+3.3–5.4 dB on test clusters) | AFP + ACP automation, Monte Carlo simulation, richest macro capacity suite | Capacity planning, traffic analysis, automatic frequency assignment | 3D traffic maps, ACP site placement | Capacity per venue (indoor scope) | Full traffic simulation incl. URLLC KPI (0.5 ms / 99.999%) |
| **Indoor / DAS** | DXF multi-wall engine, **visual DAS tree solver** (splitters/couplers/cables → exact per-antenna dB/EIRP), multi-floor stack (per-storey walls + slab loss), auto-AP placement, leaky feeder with **real datasheet cable curves**, tunnel waveguide, through-the-earth | In-Building module (add-on) | Mixed indoor/outdoor calculation | Macro focus; indoor not core | **Segment anchor**: FRT, 4–6 dB abs mean err / 3–6 dB SD uncalibrated (self-reported, 40 surveys, 700 MHz–28 GHz) | **Only tool designing indoor+outdoor simultaneously** with interaction; TETRA/PMR/P25 support |
| **Calibration (field truth)** | Drive-test **CSV/GPX ingestion → offset/slope fit → RMSE CI gates (8 dB urban / 6 dB rural)**; pipeline proven end-to-end on labelled synthetic data (replay RMSE ≈ injected σ); **real-field accuracy honestly marked unproven — the only tool whose accuracy claims anyone can reproduce** | Full drive-test/CW calibration wizard + automatic model tuning (Okumura-Hata, Cost-Hata, SPM) | Calibrated Deygout-94 self-reported at **2.56–2.99 dB SD** on Belgian TETRA (best published figure in the market, but "Best mode" ±3 dB matching flatters it) | Crowdsource + call-trace + drive-test calibration of AIM; **zero published dB figures** | Calibration module; vendor expects **0.5–2 dB gain**, calibrated accuracy explicitly out of scope of its own white paper | "Independently verified" ≤ 6 dB RMS claim with no published verification |
| **Compliance (EMF)** | **ICNIRP + FCC OET-65 ready-to-file PDF dossier** (exclusion zones, method statement, signature blocks) — one click, tested in CI | Not confirmed on vendor sources | Not confirmed on vendor sources | Not confirmed on vendor sources | Not confirmed on vendor sources | **Only incumbent with a confirmed EMF regulatory report** |
| **Price / hosting** | **$0, open source, self-hosted**; runs fully offline/air-gapped (PWA + local basemap/DEM caches); installers for Linux/macOS/Windows | Contact-sales; options (Aster, In-Building) licensed separately | Contact-sales; perpetual or subscription; USB-dongle/VM modes | Contact-sales | Contact-sales | Contact-sales |

Reference price point (the only public list pricing in the market, verified
live 2026-07-16): **Hamina** Planner $980/yr/user, Planner Plus $1,560/yr/user
— for Wi-Fi/BLE (+4G/5G and fast ray tracing in Plus). Every full-stack
incumbent above is contact-sales; industry procurement folklore puts them at
tens of thousands per seat-year, but no verifiable list price exists.

---

## 2. Kill Vectors

Factual, sourced, and specific: where AntennaMaster beats each incumbent at
its own game.

### Vs. ATDI HTZ — the exactness proof they don't publish
HTZ's 50+ model library is the broadest in the market and includes the same
NTIA ITM and ITU-R P.1812 that AntennaMaster ships. The difference is
epistemic: ATDI publishes a 102-page manual and a self-reported 2.56–2.99 dB
SD TETRA study whose correlation used a forgiving "Best mode" (±3 dB interval,
2-pixel surface matching). AntennaMaster publishes a **CI job anyone can
re-run** that proves its ITM reproduces the NTIA-published reference case to
0.0 dB and refuses to ship if deviation exceeds 0.1 dB. One is a claim; the
other is a falsifiable, reproducible proof. For the sub-6 GHz workloads that
dominate LMR/public-safety/WISP planning, the exactness argument is now
symmetric — at $0 instead of a dongle-licensed contract.

### Vs. Forsk Atoll — the calibration loop without the geodata invoice
Atoll's measurement module (drive-test import → statistical comparison →
automatic model tuning) defined the calibration workflow. AntennaMaster ships
the same loop — CSV/GPX ingestion, offset/slope fitting, prediction-vs-measured
statistics — and then goes one step Atoll does not: the fit's RMSE becomes a
**CI gate** (8 dB urban / 6 dB rural) so accuracy regressions block the build.
Atoll's clutter story assumes purchased geodata; AntennaMaster pulls ESA
WorldCover 10 m per pixel for free, and takes drone LiDAR directly. What Atoll
retains (see Concessions) is national-scale Monte Carlo and AFP/ACP maturity —
but a private-network, mine or WISP planner never needed that tier.

### Vs. Infovista Planet — numbers versus adjectives
Planet's propagation page markets an AI model and Google's propagation API and
publishes **no quantified accuracy figure at all** — the verified research
found none anywhere in its public materials, and the standard ITU-R/ITM models
are not even named on the product page. AntennaMaster's entire precision story
is numeric and regenerated on every commit: 0.0 dB ITM deviation, the official
P.1812 reference implementation, and an armed RMSE benchmark that prints its
numbers into `PRECISION_BENCHMARK.md`. When a tender asks "prove your
predictions," one of these two vendors attaches a reproducible artifact.

### Vs. iBwave Design — the DAS math without the lock-in
iBwave anchors indoor DAS and its accuracy white paper is the most detailed in
the segment (4–6 dB absolute mean error uncalibrated; calibration "expected"
to add 0.5–2 dB — calibrated accuracy explicitly out of scope). AntennaMaster
ships the same passive-DAS engineering core — splitter/coupler/cable trees
solved to exact per-antenna dB and EIRP, multi-wall prediction, multi-floor
slab losses, auto-AP placement — as open code with a 194-device catalog whose
143 datasheet-grade entries carry machine-checkable `source_url`s. No
proprietary component database subscription, no per-seat license to open your
own venue design in five years. iBwave keeps the richer 3D modeling and vendor
parts ecosystem (see Concessions); AntennaMaster removes the tollbooth from
the 80% of DAS work that is link-budget arithmetic and floor-plan prediction.

### Vs. Ranplan Professional — matching the checklist, publishing the proof
Ranplan is the only incumbent with a **confirmed EMF regulatory report** and
the only one designing indoor+outdoor jointly — credit where due. Its
accuracy claim ("within 6 dB RMS, independently verified") publishes no
verification details. AntennaMaster now matches the differentiators Ranplan
markets: EMF dossiers (ICNIRP + FCC, ready-to-file PDF), joint outdoor/indoor
workflows (shared terrain + indoor engines in one platform), TETRA/PMR/DMR
technology presets — and its 6/8 dB accuracy gates are not a marketing
sentence but an executable test. Ranplan's URLLC simulation and BIM/IFC
ingestion remain ahead (see Concessions).

### Vs. Hamina / Ekahau (Wi-Fi segment) — above the ceiling, below the price
Hamina's $980–1,560/yr/user tiers buy polished Wi-Fi/BLE planning with fast
ray tracing and private-cellular in the upper tier. AntennaMaster covers the
overlapping scope — multi-wall Wi-Fi prediction, auto-AP placement with
capacity floors, 4G/5G private-network planning — and then extends where the
Wi-Fi tools stop hard: exact ITM/P.1812 outdoor physics, microwave
availability, DAS trees, leaky feeders, tunnels, EMF dossiers. At $0/yr/user,
the question inverts: Hamina must justify the subscription against a tool
with a strict superset of physics. (Ekahau claims were not verified in this
research pass; segment logic applies.)

### Vs. the free tier (SPLAT!, Radio Mobile, CloudRF) — not verified this pass, stated carefully
These tools were named in the research scope but no claims about them survived
the verification pipeline, so this paragraph is positioning, not sourced fact:
they are the historical free/cheap options for ITM-class coverage. What none
of them offers, from AntennaMaster's measured feature set: per-pixel
WorldCover clutter into P.1812, a CI-gated exactness proof, frequency/PCI
optimization with measured SINR gain, Erlang/throughput capacity, DAS/indoor
engines, EMF dossiers, offline PWA field mode, or a provenance-audited
hardware catalog. The gap to the free tier is the whole Layer-2-to-Layer-5
stack.

---

## 3. Honest Concessions

Credibility requires stating where incumbents still win. These are real and
current:

1. **National-scale macro simulation (Atoll, Planet).** Multi-technology
   Monte Carlo over millions of subscribers, AFP/ACP across thousands of
   sites, operator-grade project databases and multi-user workflows.
   AntennaMaster's planner now handles **24-site clusters with seeded Monte
   Carlo traffic snapshots** (satisfied-user fraction with confidence
   bounds) — the private-network scale, still not the national-operator
   scale.
2. **Deterministic 3D ray tracing (iBwave FRT, Ranplan, Aster).**
   AntennaMaster's indoor engine is multi-wall (COST-231-class) plus exact
   DAS arithmetic; it does not trace reflections/diffraction paths in 3D
   geometry. In metal-heavy or highly reflective venues, calibrated ray
   tracers should outperform it. (Counterweight: iBwave's own paper shows
   uncalibrated FRT at 4–6 dB — the class advantage is smaller than marketing
   implies.)
3. **BIM/IFC ingestion (Ranplan, iBwave).** Revit/ArchiCAD/IFC import and
   automatic 2D→3D building reconstruction have no AntennaMaster equivalent;
   we ingest DXF floor plans and LiDAR point clouds.
4. **Interference coordination models (HTZ).** *Partially closed since this
   benchmark was first written:* AntennaMaster now runs the **official ITU-R
   P.452-18 reference code** (clear-air interference, 0.1–50 GHz, worst-case
   ducting percentages, WorldCover clutter input) with physics-invariant CI
   tests. P.2001, P.1546, groundwave/HF below 30 MHz and regulator-grade
   coordination *workflows* (licensing databases, batch coordination) remain
   HTZ's ground.
5. **Model breadth (HTZ).** 50+ models vs AntennaMaster's ~10 engines.
   AntennaMaster's position is depth-of-proof over breadth-of-menu, but a
   consultant needing P.533 HF circuits today needs HTZ.
6. **Vendor ecosystem & certification (iBwave).** The certified-designer
   program and OEM parts database are procurement realities in enterprise DAS
   tenders that an open catalog does not yet replace.
7. **Field-proof maturity.** ATDI can point at decades of measurement
   correlation; AntennaMaster's field RMSE gates are armed but real-campaign
   validation is, by our own benchmark's admission, **not yet proven**. We
   state it; incumbents' self-reported numbers still carry tender weight.

---

## 4. The strategic finding

The verified research's most consequential result is negative space: **no
independent, public, cross-tool accuracy benchmark exists in this market.**
Every accuracy figure that survives verification is vendor self-published,
methodologically incomparable (different bands, environments, correlation
modes), and unreproducible by customers. The market's precision discourse
runs on white papers.

AntennaMaster's position is therefore not "we are more accurate than Atoll"
— unprovable today, by anyone. It is: **we are the only platform whose
accuracy claims are executable.** Clone the repo, run the CI, watch the ITM
reference case reproduce to 0.0 dB, drop your own drive test in, and read
your own RMSE. In a market with no referee, being falsifiable is the moat.

---

*Sources: all competitor claims verified 2026-07-16 against primary vendor
sources — forsk.com (Atoll overview, CrossWave, ACP), atdi.com + ATDI
"Radio Propagation in ATDI Tools" v9.0 manual, infovista.com (Planet RF
planning, AIM), ibwave.com "Design Prediction Accuracy" white paper
(Jevremovic & Jemmali), ranplanwireless.com (Professional page + 2025
datasheet + release 6.8), hamina.com/pricing. AntennaMaster figures:
this repo — `PRECISION_BENCHMARK.md`, `GLOBAL_INVENTORY_AUDIT.md`,
`backend/tests/` (275 tests), regenerable via
`python -m tools.validate_predictions`.*
