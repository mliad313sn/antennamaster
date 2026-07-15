# AntennaMaster — Feuille de route stratégique : devenir le n° 1

> **Thèse** : chaque concurrent est n° 1 sur *un* domaine (Atoll = cellulaire,
> Pathloss = faisceaux, iBwave = intérieur, CloudRF = web, SPLAT! = ITM exact).
> Aucun n'est à la fois **gratuit, complet et précis**. AntennaMaster est déjà
> le plus **complet** et le seul vraiment **gratuit + hors ligne**. Ce document
> transforme chaque limite restante en chantier chiffré. La bataille décisive
> est la **précision prouvée** : c'est le seul des trois adjectifs que la
> concurrence peut encore nous contester.

État de départ (mesuré dans le code) : 74 points d'accès API, 43 moteurs,
209 cas de test, 6 modèles empiriques + ITM-famille, 23 préréglages,
52 équipements catalogués, UI bilingue FR/EN, 3D, télémétrie, LiDAR.

---

## Les 9 chantiers (limite → périmètre → livrables → succès)

### C1 — Clutter mondial par pixel (le grand déblocage « précision »)
**Limite actuelle** : encombrement statistique (UIT-R P.2108) — le modèle devine
la perte urbaine au lieu de la voir.
**Fait décisif** : [ESA WorldCover 10 m](https://esa-worldcover.org/en/data-access)
est **gratuit (CC-BY 4.0)**, mondial, hébergé en COG sur un
[bucket S3 public](https://registry.opendata.aws/esa-worldcover-vito/) — la même
mécanique de tuiles que notre cache SRTM.
**Périmètre** :
1. Lecteur de tuiles WorldCover (réutilise `dem/tiles.py` : cache disque + RAM LRU).
2. Table classe → hauteur représentative + perte (arbres 15 m, bâti 9–18 m,
   cultures 0 m…), méthode P.1812 « representative clutter height ».
3. Injection dans le profil : chaque échantillon reçoit sa classe ; la
   diffraction Deygout voit alors des obstacles *réels et localisés*.
4. Footprints de bâtiments **Overture/OSM** (gratuits) extrudés en DSM local
   pour les zones urbaines denses.
**Livrables** : `services/clutter/worldcover.py`, paramètre `clutter=worldcover`
sur profil/couverture, légende de classes sur la carte.
**Effort** : M (2–3 semaines). **Succès** : sur un même trajet urbain, l'écart
prédiction P.2108 vs WorldCover documenté ; RMSE mesuré en baisse (voir C8).

### C2 — ITM NTIA exact + P.1812 (la crédibilité scientifique)
**Limite actuelle** : ITM « famille » (assemblage documenté, pas le code officiel) ;
P.1546/P.452/P.1812 absents.
**Fait décisif** : le [code C++ officiel NTIA](https://github.com/NTIA/itm) est
domaine public **avec vecteurs de test** — on peut être *exact*, pas approché.
**Périmètre** :
1. Port Python fidèle (ou binding du C++) de l'ITM v1.2.2 point-à-point + zone,
   validé **au dixième de dB** contre les vecteurs NTIA publiés.
2. UIT-R **P.1812** (point-zone terrestre moderne, 30 MHz–6 GHz) — le modèle que
   les régulateurs européens exigent ; il consomme naturellement le clutter C1.
3. P.452 (brouillage trans-horizon) en second temps.
**Livrables** : `rf/itm_ntia.py` + suite de tests vecteurs, `rf/p1812.py`,
sélecteur de modèle enrichi, doc de conformité.
**Effort** : L (4–6 semaines, dominé par la validation). **Succès** : 100 % des
vecteurs NTIA ≤ 0,1 dB ; P.1812 vérifié contre les exemples du recueil UIT.

### C3 — Plan de fréquences & PCI automatique (rattraper Atoll)
**Limite actuelle** : SINR pire-cas réutilisation-1 ; pas d'affectation de canaux.
**Atout existant** : le coloriage de graphe du placement Wi-Fi (`indoor/placement.py`)
est déjà le bon algorithme — il suffit de le généraliser au multisite extérieur.
**Périmètre** :
1. Matrice d'interférence site-à-site (issue des balayages déjà calculés).
2. Affectation automatique de canaux / PCI / groupes de fréquences (coloriage
   pondéré par l'interférence, N canaux configurables).
3. SINR recalculé **après plan** (plus seulement réutilisation-1) — la carte
   montre le gain du plan.
**Livrables** : `POST /api/rf/frequency-plan`, vue « avant/après plan » dans le
panneau multisite.
**Effort** : M (2–3 semaines). **Succès** : sur un cluster 8 sites, SINR moyen
après plan > SINR réutilisation-1 + 6 dB (démontré par test).

### C4 — Capacité & trafic : Erlang + carte de débit (rattraper Atoll, 2e volet)
**Limite actuelle** : plancher de capacité AP seulement ; pas d'Erlang ni de débit.
**Périmètre** :
1. Calculateurs **Erlang B/C** (voix PMR/TETRA : canaux ↔ trafic ↔ blocage).
2. Carte de **débit** : SINR par pixel → MCS → efficacité spectrale (tables
   3GPP) × largeur de bande = Mbit/s par pixel ; agrégation par cellule.
3. Couche de demande (utilisateurs/km², trafic par usager) → cellules saturées
   surlignées, suggestion de densification.
**Livrables** : `rf/capacity.py`, `POST /api/rf/throughput-map`, onglet
« Capacité » dans le panneau d'étude.
**Effort** : M (3 semaines). **Succès** : carte de débit validée contre les
tables 3GPP ; scénario de saturation reproduit en test.

### C5 — Disponibilité faisceaux complète (rattraper Pathloss)
**Limite actuelle** : double-k + pluie/gaz, mais pas de **% de disponibilité**.
**Périmètre** :
1. Évanouissement par multitrajet UIT-R **P.530** (facteur géoclimatique,
   probabilité de fade > marge).
2. Indisponibilité pluie via zones **P.837** + P.838 (déjà présent) → % annuel.
3. Améliorations de diversité (espace/fréquence), objectif de bond (99,99x %).
**Livrables** : `rf/availability.py`, bloc « Disponibilité annuelle » dans
l'étude PtP + rapport PDF.
**Effort** : M (2–3 semaines). **Succès** : concordance ≤ 0,5 dB de marge avec
les exemples publiés P.530 ; un bond 18 GHz affiche son 99,99x %.

### C6 — Intérieur profond : étages empilés + arbre DAS (rattraper iBwave)
**Limite actuelle** : multi-murs 2D mono-étage ; pénétration d'étage statistique ;
pas de chaîne DAS composant par composant.
**Périmètre** :
1. **Pile d'étages** : un plan DXF par étage, TX sur l'étage i, carte sur
   l'étage j (traversées de dalles réelles + murs de l'étage cible).
2. **Arbre DAS** : bibliothèque splitters/coupleurs/câbles (le catalogue C7 les
   accueille déjà : `equipment_class` extensible), budget de liaison le long de
   l'arbre, puissance réelle à chaque antenne, heatmap combinée multi-antennes.
3. Multi-TX indoor (déjà quasi prêt via `auto_place_aps` → rendu combiné).
**Livrables** : `indoor/das.py`, éditeur d'arbre DAS simple dans le studio,
classe `das_component` au catalogue.
**Effort** : L (4–6 semaines — le plus gros chantier UI). **Succès** : un
immeuble 3 étages + DAS 8 antennes se conçoit de bout en bout dans l'outil.

### C7 — Catalogue 500+ équipements **vérifiés fiche technique**
**Limite actuelle** : 52 entrées dont 1 seule vérifiée datasheet ; le reste en
« référence de classe » (honnête mais insuffisant pour « précis »).
**Atout existant** : pipeline d'ingestion + dédoublonnage + `spec_confidence`
déjà en production.
**Périmètre** :
1. Campagne datasheet : par lots vendeur (RFS, CommScope, Motorola, Cambium…),
   chaque lot vérifié contre le PDF constructeur, `spec_confidence=datasheet`.
2. Diagrammes MSI associés aux antennes du catalogue (le moteur les lit déjà).
3. Contribution communautaire : schéma JSON publié + validation CI automatique.
**Livrables** : 500+ entrées dont ≥ 60 % datasheet ; workflow de contribution.
**Effort** : continu (S par lot). **Succès** : compteur `by_confidence` public
dans `GLOBAL_INVENTORY_AUDIT.md` ; zéro spec inventée.

### C8 — Précision **prouvée** : banc de validation public (l'arme du n° 1)
**Limite actuelle** : la physique est testée unitairement, mais aucune
comparaison publiée prédiction ↔ mesures réelles. C'est CE chantier qui
autorise le mot « précis ».
**Périmètre** :
1. Ingestion de jeux de mesures publics (drive tests ouverts, données Ofcom/
   FCC/universitaires) via l'endpoint de calibration existant.
2. Rapport automatique : **RMSE / biais par modèle et par environnement**,
   publié dans le dépôt (`PRECISION_BENCHMARK.md`) et régénéré en CI.
3. Boucle : la calibration terrain (déjà livrée) nourrit des corrections par
   région stockées et versionnées.
**Livrables** : `tools/validate_predictions.py`, benchmark public, badge de
précision dans le README.
**Effort** : M (3 semaines + continu). **Succès** : RMSE publié ≤ 8 dB urbain /
≤ 6 dB rural (état de l'art des modèles empiriques calibrés) ; ITM = vecteurs
NTIA exacts (C2).

### C9 — Rapports réglementaires & coordination
**Limite actuelle** : PDF de marque généraliste ; rien de formaté régulateur.
**Périmètre** : gabarits de rapport par usage (dossier EMF ICNIRP/OET-65 —
moteur déjà livré ; fiche de coordination faisceau ; dossier de brouillage
P.452 après C2). Honnêteté : l'outil produit des dossiers *au format attendu* ;
la certification légale reste celle du bureau d'études qui signe.
**Effort** : S–M (2 semaines). **Succès** : un dossier EMF prêt à déposer sort
en un clic.

---

## Roadmap de synthèse

| Phase | Chantiers | Durée indicative | Ce que la phase débloque |
|---|---|---|---|
| **P1 — Précision** | C1 WorldCover + C2 ITM/P.1812 + C8 benchmark | ~2 mois | Le droit de dire « précis » avec preuves publiques ; parité SPLAT! dépassée |
| **P2 — Profondeur cellulaire** | C3 plan de fréquences + C4 capacité/débit | ~1,5 mois | Parité Atoll sur les réseaux privés 4G/5G (le segment qui croît) |
| **P3 — Profondeur faisceaux & intérieur** | C5 disponibilité P.530 + C6 étages/DAS | ~2 mois | Parité Pathloss (dispo annuelle) et iBwave-lite (DAS de bout en bout) |
| **P4 — Écosystème** | C7 catalogue 500+ + C9 rapports + communauté | continu | L'effet réseau : données + contributeurs que personne ne rattrape |

Chaque chantier suit la discipline déjà en place : moteur + endpoint + tests
anchorés + i18n FR/EN + doc — rien n'est « démo ».

---

## Positionnement cible (après P1–P3)

| Critère | Atoll | Pathloss | iBwave | CloudRF | SPLAT! | **AntennaMaster** |
|---|---|---|---|---|---|---|
| Gratuit / auto-hébergé | ✗ | ✗ | ✗ | ✗ | ✓ | **✓** |
| Extérieur macro précis (clutter pixel + ITM exact + P.1812) | ✓ | ~ | ✗ | ~ | ~ | **✓ (P1)** |
| Plan de fréquences + capacité | ✓ | ✗ | ✗ | ✗ | ✗ | **✓ (P2)** |
| Faisceaux avec % dispo | ~ | ✓ | ✗ | ~ | ✗ | **✓ (P3)** |
| Intérieur multi-étages + DAS | ✗ | ✗ | ✓ | ✗ | ✗ | **✓ (P3)** |
| Tunnel / mine / TTE / leaky feeder | ✗ | ✗ | ~ | ✗ | ✗ | **✓ (déjà)** |
| Bidirectionnel LMR + DAQ | ✗ | ✗ | ✗ | ✗ | ✗ | **✓ (déjà)** |
| 3D + LiDAR + télémétrie temps réel | ~ | ✗ | ~ | ~ | ✗ | **✓ (déjà)** |
| Hors ligne / terrain / bilingue / IA | ✗ | ✗ | ✗ | ✗ | ✗ | **✓ (déjà)** |

**La phrase de positionnement** (à n'utiliser qu'une fois P1 livrée) :
> *AntennaMaster est la seule plateforme de planification radio à la fois
> **gratuite** (open, auto-hébergeable, hors ligne), **complète** (du macro 5G
> au fond de mine, du faisceau hertzien au DAS) et **précise** (ITM NTIA exact,
> clutter mondial 10 m, précision publiée et vérifiable contre mesures).*

## KPI « numéro 1 » (mesurables, pas déclaratifs)

1. **Précision** : RMSE publié ≤ 8 dB urbain / ≤ 6 dB rural ; ITM ≤ 0,1 dB des
   vecteurs NTIA ; benchmark régénéré en CI à chaque release.
2. **Complétude** : 100 % des cas d'usage de la matrice ci-dessus couverts par
   un moteur testé (aujourd'hui : 7/9 lignes).
3. **Confiance des données** : ≥ 60 % du catalogue en `datasheet`, 0 spec
   inventée.
4. **Adoption** : installations auto-hébergées, contributions communautaires au
   catalogue, citations du benchmark de précision.

## Risques & honnêteté

- **C2 est le chantier le plus risqué** (validation longue) mais le plus
  rentable en crédibilité — le faire en premier, pas en dernier.
- « Précis » sans C8 (benchmark public) resterait un slogan : les deux vont
  ensemble ou pas du tout.
- iBwave garde l'avantage sur le 3D bâtiment photoréaliste ; C6 vise le
  « suffisant pour concevoir », pas la parité cosmétique.
- La certification réglementaire est un statut légal, pas une fonctionnalité :
  C9 produit des dossiers au bon format, le mot « certifié » ne sera jamais
  employé abusivement.
