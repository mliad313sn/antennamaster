# AntennaMaster — Definitive Enterprise Architecture Roadmap (Execution Tracker)

Transitioning AntennaMaster from a **Layer 1 prediction tool** into a
**Layer 5 intelligent design & compliance platform**. Each phase ships real,
tested code with documented API endpoints before the next begins.

Baseline at kickoff: **139 backend tests passing**.

| Phase | Scope | Status |
|---|---|---|
| **1** | Bidirectional "Talk-Back" & LMR repeaters | 🟢 Complete |
| **2** | Metro/Mine leaky feeder (radiating cable) | 🟢 Complete |
| **3** | Automated AP/site placement solver | ⬜ Not started |
| **4** | Intelligent Copilot & MCP integration | ⬜ Not started |
| **5** | Compliance (EMF), ITM & drive-test calibration | ⬜ Not started |

---

## Phase 1 — Bidirectional "Talk-Back" & LMR Repeaters

**Goal:** move from downlink-only prediction to two-way system design with
delivered-audio-quality (DAQ) grading and repeater engineering.

Deliverables:
- [x] `services/rf/talkback.py` — portable-radio profiles, bidirectional
      (talk-out / talk-in) link balance on a reciprocal terrain path, TIA-4046
      DAQ grading, repeater donor isolation / max stable gain / cascade spacing.
- [x] Portable profiles: body loss (3–6 dB), 1.5 m antenna height, building
      penetration classes, per-device EIRP.
- [x] DAQ intersection: combined DAQ = min(talk-out DAQ, talk-in DAQ).
- [x] Repeater module: donor isolation estimate, feedback-stable max gain,
      cascade spacing for continuous talk-back.
- [x] API: `GET /api/rf/portable-profiles`, `POST /api/rf/talkback`,
      `POST /api/rf/talkback/batch`, `POST /api/rf/repeater/design`.
- [x] Tests: `tests/test_talkback.py`.

---

## Phase 2 — Metro/Mine Leaky Feeder (Radiating Cable)

**Goal:** model the radiating-cable systems that actually deliver continuous
coverage in tunnels, metros and underground mines (not just free-space waveguide).

Deliverables:
- [x] `services/rf/underground.py` extended: frequency-scaled longitudinal
      cable loss (dB/m, ~√f skin effect), coupling loss, radial spreading.
- [x] Auto inline-amplifier spacing to hold a target design margin, with
      gain-limited restoration and amplifier placement list.
- [x] "Moving-train" KPI: percent of run above threshold + worst coverage gap.
- [x] Cable length measured directly from a designated DXF polyline layer
      (`floorplan.layer_polyline_length`).
- [x] API: `GET /api/indoor/leaky-cables`, `POST /api/indoor/leaky-feeder`.
- [x] Tests: `tests/test_leaky_feeder.py` (9 tests).
## Phase 3 — Automated AP/Site Placement Solver  *(pending)*
## Phase 4 — Intelligent Copilot & MCP Integration  *(pending)*
## Phase 5 — Compliance, ITM & Calibration  *(pending)*
