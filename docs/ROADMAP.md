# AntennaMaster — Capability Roadmap / Feuille de route

> Bilingual document — English first, then French. / Document bilingue —
> anglais d'abord, puis français.

---

# 🇬🇧 English

## Where AntennaMaster sits: the five-layer model

An RF platform spans five layers of value. AntennaMaster began almost entirely
in Layer 1 (a strong *propagation predictor*). This roadmap took it up the
ladder — Layers 2, 3, 4 and 5 are now implemented.

| Layer | Question | Status |
|---|---|---|
| **1. Prediction** | "How far does the signal go?" | 🟢 Mature (empirical + 3GPP + Deygout + ITM) |
| **2. System design** | "What equipment, where, how many, wired how?" | 🟢 Delivered (two-way, leaky feeder, DAS) |
| **3. Optimization** | "*Solve* for the best design under constraints" | 🟢 Delivered (auto-placement, channel plan, site-search) |
| **4. Compliance & ops** | "EMF safety, calibration, procurement" | 🟢 Delivered (EMF, drive-test calibration) |
| **5. Intelligence** | "An AI copilot that ties 1–4 together" | 🟢 Delivered (engine-driven advisor + tool API) |

## What was closed (the red rows of the original audit)

| Gap | Now | Engine / endpoint |
|---|---|---|
| **Two-way talk-back** (repeater ↔ portable) | Talk-out **and** talk-in, limited by the weaker direction; DAQ (TIA-4046) grading; body/penetration losses; repeater cascade | `rf/twoway.py` — `/api/rf/twoway/{link,coverage,repeater-cascade}` |
| **Leaky feeder / radiating cable** | Longitudinal + coupling loss, inline-amp spacing, bend loss, served-length/worst-gap KPIs; DAS designer | `rf/leakyfeeder.py` — `/api/indoor/{leaky-feeder,tunnel-das}` |
| **Automated AP/site placement** | Greedy set-cover placement, graph-colour channel plan, capacity floor, roaming overlap | `indoor/placement.py` — `/api/indoor/auto-place` |
| **AI copilot** | Engine-driven, air-gapped diagnosis with quantified fixes; agent tool catalog; optional Claude narrator | `copilot/` — `/api/copilot/{tools,analyze/link,analyze/coverage}` |
| **RF-exposure / EMF (ICNIRP / FCC OET-65)** | Public/occupational exclusion-zone distances, exposure ratios | `rf/compliance.py` — `/api/rf/compliance` |
| **Longley-Rice / ITM** | Irregular-terrain path loss with a reliability quantile (time/situation) | `rf/itm.py` — `/api/terrain/itm` |
| **Measurement calibration (drive test)** | Fit offset / offset+slope from measured RSSI; RMS before/after | `rf/calibration.py` — `/api/rf/calibrate` |

## Delivered phases

- **Phase 1 — Two-way talk-back + DAQ.** By reciprocity, talk-in and talk-out
  received power differ only by the TX-power swap, so one downlink sweep yields
  both directions. Unlocks LMR/mining/public-safety tenders written in DAQ +
  talk-in/talk-out terms.
- **Phase 2 — Leaky feeder & distributed antennas.** The *actual* metro /
  underground-mine deliverable, grafted onto the existing Emslie waveguide.
- **Phase 3 — Auto AP/site placement.** The iBwave-differentiator: the scoring
  engine already existed; this adds the optimizer, channel plan, capacity and
  roaming on top.
- **Phase 4 — AI copilot.** The MCP/tool-API is the durable foundation
  (existing endpoints exposed as callable tools); the deterministic advisor
  sits on top and runs offline; a Claude narrator is optional.
- **Phase 5 — Compliance, ITM, calibration.** EMF gates permits; ITM closes
  the one admitted model gap; calibration turns predictions into *trusted*
  predictions.

## Design principles honoured

- **Reuse over rebuild.** Two-way reuses the coverage sweep; auto-placement
  reuses the multi-wall engine as its cost function; ITM reuses the validated
  Deygout diffraction; the copilot calls the height optimizer.
- **Verifiable correctness.** Every engine has anchored unit tests
  (knife-edge = 6.02 dB, median deviate = 0, reciprocity invariant, inverse-
  square exposure, greedy coverage monotonicity). +43 new tests, 182 total.
- **Honest scope.** Heuristics (DAQ offsets, ITM assembly) are documented as
  engineering models, not measured curves; the ITM median reuses validated
  physics rather than an unverifiable byte-exact NTIA port.
- **Air-gapped by default.** The copilot advises with no API key or network;
  a local model can back the narrator for isolated mine sites.

## Future directions (not yet built)

- Real per-pixel clutter (ESA WorldCover + OSM/Overture building footprints)
  as 3D obstructions, replacing statistical P.2108.
- Capacity/traffic dimensioning (Erlang, throughput maps) beyond the AP floor.
- Vision-assisted plan/photo reading to pre-fill wall materials and mast sites.
- Agentic optimization: the copilot driving site-search/auto-placement toward
  a stated coverage-vs-CAPEX objective.

---

# 🇫🇷 Français

## Le positionnement d'AntennaMaster : le modèle en cinq couches

Une plateforme RF couvre cinq couches de valeur. AntennaMaster est parti
presque entièrement de la couche 1 (un solide *prédicteur de propagation*).
Cette feuille de route l'a fait monter d'un cran — les couches 2, 3, 4 et 5
sont désormais implémentées.

| Couche | Question | État |
|---|---|---|
| **1. Prédiction** | « Jusqu'où porte le signal ? » | 🟢 Mature (empirique + 3GPP + Deygout + ITM) |
| **2. Conception système** | « Quel matériel, où, combien, câblé comment ? » | 🟢 Livré (bidirectionnel, câble rayonnant, DAS) |
| **3. Optimisation** | « *Résoudre* la meilleure conception sous contraintes » | 🟢 Livré (placement auto, plan de canaux, recherche de site) |
| **4. Conformité & exploitation** | « Sécurité EMF, calibration, achats » | 🟢 Livré (EMF, calibration terrain) |
| **5. Intelligence** | « Un copilote IA reliant 1 à 4 » | 🟢 Livré (conseiller piloté par les moteurs + API d'outils) |

## Ce qui a été comblé (les lignes rouges de l'audit initial)

| Manque | Désormais | Moteur / point d'accès |
|---|---|---|
| **Bidirectionnel (répéteur ↔ portatif)** | Émission **et** réception, limité par le sens le plus faible ; notation DAQ (TIA-4046) ; pertes corps/pénétration ; cascade de répéteurs | `rf/twoway.py` — `/api/rf/twoway/{link,coverage,repeater-cascade}` |
| **Câble rayonnant (leaky feeder)** | Pertes longitudinale + de couplage, espacement des amplis en ligne, pertes de courbure, KPI longueur desservie/pire trou ; concepteur DAS | `rf/leakyfeeder.py` — `/api/indoor/{leaky-feeder,tunnel-das}` |
| **Placement automatique des points d'accès** | Placement glouton par couverture, plan de canaux par coloration de graphe, plancher de capacité, recouvrement de roaming | `indoor/placement.py` — `/api/indoor/auto-place` |
| **Copilote IA** | Diagnostic piloté par les moteurs, hors-ligne, avec correctifs chiffrés ; catalogue d'outils pour agent ; narrateur Claude optionnel | `copilot/` — `/api/copilot/{tools,analyze/link,analyze/coverage}` |
| **Exposition RF / EMF (ICNIRP / FCC OET-65)** | Distances des zones d'exclusion public/professionnel, ratios d'exposition | `rf/compliance.py` — `/api/rf/compliance` |
| **Longley-Rice / ITM** | Affaiblissement en terrain irrégulier avec un quantile de fiabilité (temps/situation) | `rf/itm.py` — `/api/terrain/itm` |
| **Calibration par mesures (drive test)** | Ajustement décalage / décalage+pente depuis des RSSI mesurés ; RMS avant/après | `rf/calibration.py` — `/api/rf/calibrate` |

## Phases livrées

- **Phase 1 — Bidirectionnel + DAQ.** Par réciprocité, les puissances reçues
  en émission et en réception ne diffèrent que du décalage de puissance
  d'émission : un seul balayage descendant donne les deux sens. Débloque les
  appels d'offres LMR/minier/sécurité publique rédigés en DAQ.
- **Phase 2 — Câble rayonnant & antennes distribuées.** Le *vrai* livrable
  métro / mine souterraine, greffé sur le guide d'ondes Emslie existant.
- **Phase 3 — Placement automatique.** Le différenciateur type iBwave : le
  moteur de notation existait déjà ; on y ajoute l'optimiseur, le plan de
  canaux, la capacité et le roaming.
- **Phase 4 — Copilote IA.** L'API d'outils (MCP) est la base durable (points
  d'accès existants exposés comme outils appelables) ; le conseiller
  déterministe fonctionne hors-ligne ; le narrateur Claude est optionnel.
- **Phase 5 — Conformité, ITM, calibration.** L'EMF conditionne les permis ;
  l'ITM comble le seul manque de modèle reconnu ; la calibration rend les
  prédictions *fiables*.

## Principes de conception respectés

- **Réutiliser plutôt que reconstruire.** Le bidirectionnel réutilise le
  balayage de couverture ; le placement auto réutilise le moteur multi-murs
  comme fonction de coût ; l'ITM réutilise la diffraction Deygout validée ; le
  copilote appelle l'optimiseur de hauteurs.
- **Exactitude vérifiable.** Chaque moteur a des tests unitaires ancrés
  (arête = 6,02 dB, déviée médiane = 0, invariant de réciprocité, exposition en
  inverse du carré, monotonie de la couverture gloutonne). +43 tests, 182 au
  total.
- **Périmètre honnête.** Les heuristiques (offsets DAQ, assemblage ITM) sont
  documentées comme modèles d'ingénierie, non comme courbes mesurées ; la
  médiane ITM réutilise une physique validée plutôt qu'un portage NTIA exact
  invérifiable.
- **Hors-ligne par défaut.** Le copilote conseille sans clé API ni réseau ; un
  modèle local peut alimenter le narrateur sur les sites miniers isolés.

## Orientations futures (non encore réalisées)

- Clutter réel par pixel (ESA WorldCover + empreintes de bâtiments
  OSM/Overture) comme obstructions 3D, en remplacement du P.2108 statistique.
- Dimensionnement capacité/trafic (Erlang, cartes de débit) au-delà du plancher
  de points d'accès.
- Lecture assistée par vision des plans/photos pour pré-remplir les matériaux
  de murs et les emplacements de mâts.
- Optimisation agentique : le copilote pilotant recherche-de-site/placement-
  auto vers un objectif couverture/CAPEX donné.
