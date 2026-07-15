# AntennaMaster — Definitive Enterprise Architecture Roadmap (Execution Tracker)

Transitioning AntennaMaster from a **Layer 1 prediction tool** into a
**Layer 5 intelligent design & compliance platform**. Each phase ships real,
tested code with documented API endpoints before the next begins.

Baseline at kickoff: **139 backend tests passing**.

| Phase | Scope | Status |
|---|---|---|
| **1** | Bidirectional "Talk-Back" & LMR repeaters | 🟢 Complete |
| **2** | Metro/Mine leaky feeder (radiating cable) | 🟢 Complete |
| **3** | Automated AP/site placement solver | 🟢 Complete |
| **4** | Intelligent Copilot & MCP integration | 🟢 Complete |
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
## Phase 3 — Automated AP/Site Placement Solver

**Goal:** invert the coverage problem — solve for AP count, positions and
channels instead of scoring a hand-placed layout.

Deliverables:
- [x] `services/rf/apsolver.py`: demand/candidate grids, indoor RSSI builder
      (FSPL + COST-231 multi-wall, ITU-R P.1238 fallback) and outdoor builder.
- [x] Greedy max-coverage placement ((1−1/e) set-cover heuristic).
- [x] Capacity sizing: adds APs for user-density and throughput demand
      (Wi-Fi 6/7 users-per-AP + per-AP Mbps).
- [x] Roaming enforcement: −67 dBm secondary-AP overlap fraction.
- [x] Channel assignment: Welsh-Powell graph colouring over 2.4/5/6 GHz
      non-overlapping channel sets; co-channel conflict count.
- [x] Output: AP [x, y, z], channel, served demand points.
- [x] API: `POST /api/indoor/ap-solve`.
- [x] Tests: `tests/test_apsolver.py` (8 tests).
## Phase 4 — Intelligent Copilot & MCP Integration

**Goal:** an AI Design Copilot that *runs* the simulation engines, plus MCP
tool exposure so external agents can too.

Deliverables:
- [x] `services/ai/tools.py`: MCP-format tool registry over the self-contained
      engines (technologies, models, link budget, repeater, leaky feeder,
      tunnel, TTE) with pure handlers.
- [x] `services/ai/copilot.py`: agentic loop on the Anthropic Messages API via
      `httpx` (no SDK dep; base-URL override for local/air-gapped LLMs);
      **injectable transport** for offline testing; graceful when unconfigured.
- [x] Vision: `propose_from_floorplan` — wall materials + candidate AP/mast
      locations from a floor-plan image (tolerant JSON parsing).
- [x] `backend/mcp_server.py`: optional stdio MCP server (guarded SDK import).
- [x] API: `GET /api/ai/status`, `GET /api/ai/tools`, `POST /api/ai/tools/{name}`,
      `POST /api/ai/chat`, `POST /api/ai/vision/floorplan`.
- [x] Tests: `tests/test_copilot.py` (13 tests, agentic loop verified with a
      scripted transport — no network).

**Configuration:** set `AM_ANTHROPIC_API_KEY` (or `ANTHROPIC_API_KEY`);
optional `AM_COPILOT_MODEL` (default `claude-sonnet-5`), `AM_LLM_BASE_URL`
(local/proxy endpoint), `AM_COPILOT_MAX_TOKENS`.
## Phase 5 — Compliance, ITM & Calibration  *(pending)*
