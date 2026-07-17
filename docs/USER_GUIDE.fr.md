# AntennaMaster — Guide complet de l'utilisateur

Tout ce que vous pouvez faire avec AntennaMaster, chaque réglage qu'il expose,
et ce que chacun signifie. Tous les chiffres de ce guide sont tirés directement
du code.

Documents complémentaires :
- `README.md` — aperçu rapide et architecture
- `INSTALL_GUIDE.md` — installation et lancement multiplateforme (Windows/macOS/Linux)
- `docs/CAPABILITIES.md` — matrice condensée des capacités
- `docs/ROADMAP.md` — modèle de capacités en cinq couches et phases livrées
- `VISION_ARCHITECTURE.md` — jumeau numérique 3D, télémétrie en direct, LiDAR
- `SaaS_ARCHITECTURE.md` — internes multi-locataires / SaaS
- `http://localhost:8010/docs` — référence OpenAPI interactive en direct

---

## Table des matières

1. [Prise en main](#1-prise-en-main)
2. [Le planificateur (écran principal)](#2-le-planificateur)
3. [Flux de travail terrain DXF](#3-flux-dxf)
4. [Études radio point à point](#4-etudes-point-a-point)
5. [Simulation de couverture de zone](#5-couverture-de-zone)
6. [Cartes multisites « meilleur serveur »](#6-multisites)
7. [Diagrammes d'antenne](#7-antennes)
8. [Studio intérieur et souterrain](#8-interieur-souterrain)
9. [Lecture du graphe de profil](#9-graphe-de-profil)
10. [Comptes, rôles et tableaux de bord](#10-comptes-roles)
11. [Projets, partage et rapports](#11-projets-partage)
12. [Niveaux d'abonnement](#12-niveaux)
13. [Référence : préréglages technologiques](#13-prereglages)
14. [Référence : modèles de propagation](#14-modeles)
15. [Référence : matériaux et préréglages](#15-materiaux)
16. [Référence : chaque réglage](#16-chaque-reglage)
17. [Configuration serveur (variables d'environnement)](#17-configuration-serveur)
18. [Limites et capacités](#18-limites)
19. [Dépannage](#19-depannage)
20. [Modules avancés, jumeau numérique 3D et opérations en direct](#20-modules-avances)

---

## 1. Prise en main

### Démarrage en une commande

```bash
./install.sh          # macOS/Linux : analyse l'hôte, installe les runtimes manquants, compile
./launch.sh           # démarre les deux serveurs, attend la santé, ouvre le navigateur
```

Sous Windows, utilisez `install.ps1` / `launch.ps1` (PowerShell). L'installateur
résout automatiquement Python 3.10+, Node 18+ et les outils de compilation ;
voir `INSTALL_GUIDE.md` pour la matrice complète. Pour le développement, vous
pouvez toujours utiliser :

```bash
./start.sh            # installe les dépendances au besoin, démarre backend :8000 + frontend :3000
./start.sh --check    # lance d'abord la validation QA complète (tests backend, benchmarks, tests frontend)
```

### Démarrage manuel

Backend (Python ≥ 3.11) :

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

Frontend (Node ≥ 18 ; proxifie `/api/*` vers le backend via `BACKEND_URL`,
par défaut `http://localhost:8010`) :

```bash
cd frontend
npm install
npm run build && npm start     # ou : npm run dev
```

Ouvrez **http://localhost:3010**. L'API REST est auto-documentée à l'adresse
**http://localhost:8010/docs**.

### Sondes de santé

- `GET /api/health` — vivacité (liveness).
- `GET /api/ready` — disponibilité (répertoire de données accessible en écriture, état du cache MNT).

### Première étude en 30 secondes

1. Cliquez une fois sur la carte pour placer l'**émetteur (TX)**, cliquez de nouveau pour le **récepteur (RX)**.
2. Le profil du terrain, le verdict de ligne de visée et le dégagement de
   Fresnel apparaissent automatiquement — aucun DXF ni compte requis, partout
   sur Terre (SRTM 30 m).
3. Choisissez un préréglage technologique (p. ex. *LTE 800*) dans le panneau
   **Étude radio** pour transformer le profil en un bilan de liaison complet
   avec la puissance reçue par échantillon.

---

## 2. Le planificateur (écran principal)

### Langue, Mode Simple et visite guidée

- **Langue** — l'en-tête comporte un sélecteur **EN / FR**. L'anglais et le
  français sont fournis d'origine ; votre choix est mémorisé. (Ajouter une
  langue revient à créer un fichier `locales/<code>/common.json`.)
- **Simple ↔ Expert** — le bouton de l'en-tête. Le **Mode Simple** masque les
  chiffres RF (dBi, MHz, modèle de propagation) et demande plutôt *« que
  cherchez-vous à connecter ? »* — choisissez un objectif (relier deux
  bâtiments, Wi-Fi pour une flotte de véhicules, radios portatives sur un site,
  4G/5G privée, capteurs IoT, couverture mobile, faisceau longue distance) et la
  bonne technologie et les bons réglages sont appliqués pour vous. Le mode
  **Expert** expose toutes les commandes.
- **Visite guidée** — les nouveaux visiteurs bénéficient d'un court parcours
  (placer les points → choisir une technologie → importer un DXF → lire la carte
  thermique). Rejouez-la à tout moment avec le bouton **❓**.
- **Info-bulles du glossaire** — chaque champ technique porte une icône **ⓘ**.
  Survolez-la, mettez-la au focus ou touchez-la pour une explication en langage
  clair, sans équations (également traduite).

### Carte et fournisseurs

| Réglage | Rôle |
|---|---|
| Sélecteur de fond de carte | 6 fournisseurs intégrés : OpenStreetMap, OpenTopoMap, Carto Light, Carto Dark, Esri World Imagery, Esri World Topo |
| URL XYZ personnalisée | Tout gabarit de tuiles `{z}/{x}/{y}` (serveurs de tuiles privés, orthophotos…) |
| Bascule de thème | auto (suit l'OS) → sombre → clair ; persistant |
| Langue | Anglais / Français ; persistant |

La vue de la carte (centre/zoom) et l'ensemble de la session (points, réglages
d'étude, référence DXF) persistent dans `localStorage` et sont restaurés au
rechargement.

### Placer l'émetteur et le récepteur

- **Cliquez** sur la carte : le premier clic place le TX, le second le RX ; les clics suivants déplacent le RX.
- **Saisie de coordonnées exactes** : les champs lat/lon TX/RX acceptent la
  frappe libre (les valeurs s'appliquent lorsqu'elles sont analysables ; vous
  pouvez vider le champ pendant l'édition).
- **GPS** : *Utiliser ma position* place le TX à partir de la géolocalisation du
  navigateur (avec une erreur visible si la permission est refusée).
- **Inverser** : échange TX et RX en un clic.
- **Recherche** : saisissez `lat, lon` directement ou un nom de lieu (géocodé
  via OpenStreetMap Nominatim — nécessite Internet).

### Hauteurs d'antenne

`Hauteur TX` et `Hauteur RX` sont en mètres **au-dessus du sol** à chaque
extrémité. Laissez un préréglage technologique sélectionné et les hauteurs sont
préremplies avec des valeurs réalistes (p. ex. mât 30 m / portatif 1,5 m pour le GSM).

### Réglages de profil

| Réglage | Plage | Défaut | Signification |
|---|---|---|---|
| Échantillons | 16–2 048 | 256 | points le long du trajet géodésique |
| facteur k | 0,1–10 | 1,333 | facteur de rayon terrestre effectif ; 4/3 = atmosphère standard, 0,7 ≈ sous-réfraction pire cas, 2+ ≈ conduit (ducting) |
| Profondeur de feuillage | 0–400 m | 0 | végétation traversée par le trajet (modèle Weissberger) |
| Taux de pluie | 0–150 mm/h | 0 | affaiblissement dû à la pluie (UIT-R P.838/P.530), significatif au-dessus de ~7 GHz |
| Encombrement %loc | 0–99,9 | 0 (désactivé) | encombrement statistique d'origine humaine UIT-R P.2108 ; 50 = urbain médian, 90 = conservateur |
| Modèle de surface | on/off | off | échantillonne un MNS (bâtiments comme obstacles) ; visible uniquement si `AM_DSM_URL` est configuré |

Le profil se recalcule automatiquement (avec anti-rebond ~350 ms) à chaque
changement d'entrée. **Exporter en CSV** télécharge le tableau complet par
échantillon avec les mêmes paramètres d'étude appliqués.

---

## 3. Flux de travail terrain DXF

Un DXF est une *surcharge locale* : AntennaMaster fonctionne globalement sur le
SRTM seul, et un DXF géoréférencé applique un relief de plus haute résolution à
l'intérieur de son emprise.

### Étape 1 — Import

Glissez-déposez (ou parcourez) un fichier `.dxf` dans l'assistant. Limite :
**100 Mo** (`AM_MAX_DXF_MB`). Les fichiers endommagés passent par le chargeur de
récupération d'ezdxf.

La réponse d'import inclut des **indices auto-détectés** : les magnitudes de
coordonnées sont analysées pour suggérer une zone UTM probable ou un dessin en
pieds, et l'assistant préremplit le mode de géoréférencement en conséquence.

### Étape 2 — Choisir les calques de terrain

Chaque calque est listé avec ses types d'entités, son nombre de points et sa
plage Z, plus une heuristique de « ressemblance au terrain » qui présélectionne
les calques de relief plausibles. L'altitude est extraite de :

- entités `POINT` (points de levé)
- `LWPOLYLINE` avec un attribut `elevation` (courbes de niveau)
- `POLYLINE` — polylignes 2D/3D, maillages polyface, maillages de polygones
- `3DFACE` et `MESH`
- cotes d'altitude `TEXT`/`MTEXT` (analysées par expression régulière, préfixes `EL=`/`H=` pris en charge)

Les points XY en double sont dédupliqués ; le nuage dispersé est maillé avec
`scipy.griddata` (linéaire, repli au plus proche voisin en frange d'enveloppe)
sur une grille adaptée à la densité, d'au plus 400×400 cellules.

### Étape 3 — Géoréférencement (trois modes)

| Mode | Vous fournissez | Idéal quand |
|---|---|---|
| **CRS connu** | code EPSG ou chaîne PROJ (p. ex. `EPSG:32633`) | le dessin est dans un CRS projeté documenté (UTM, Lambert, plan d'État) |
| **Points de calage** | 2–3 paires DXF X/Y ↔ Lat/Lon réelles | vous pouvez identifier des coins/repères levés dans le dessin |
| **Origine + azimut** | Lat/Lon d'ancrage, azimut vrai de l'axe +Y, unité (m/ft/yd/cm), décalage d'origine optionnel | vous savez où se trouve l'origine du dessin et son orientation |

Les points de calage résolvent une transformation **Helmert** 2D par moindres
carrés (échelle + rotation + translation) dans un plan local et rapportent les
**résidus par point et le RMS en mètres** — si un résidu est grand, ce point de
calage est erroné. Un `z_scale` indépendant convertit les unités verticales
(p. ex. `0.3048` pour des altitudes en pieds).

### Validation et fusion

Après géoréférencement, l'altitude DXF moyenne est recoupée avec l'altitude SRTM
moyenne sur la même emprise. Un écart supérieur à **50 m**
(`AM_VALIDATION_DIFF_M`) déclenche un avertissement strict — les causes
classiques sont une confusion pieds/mètres ou un CRS erroné.

Dans les profils et la couverture, le DXF l'emporte à l'intérieur de sa boîte
englobante ; sur une **bande de fondu de 3 cellules** (`AM_FEATHER_CELLS`) les
surfaces DXF et SRTM sont mélangées afin que la couture ne crée jamais une fausse
arête de diffraction. Chaque échantillon de profil porte sa provenance (`srtm` /
`blend` / `dxf`), que le graphe colore en bleu/orange.

La carte affiche le **polygone d'emprise** du DXF et une **superposition
d'ombrage** semi-transparente (teinte hypsométrique × ombrage analytique) pour
voir exactement le terrain apporté par le DXF. L'état DXF est persisté côté
serveur et reconstruit automatiquement après un redémarrage.

---

## 4. Études radio point à point

Sélectionnez un **préréglage technologique** dans le panneau Étude radio (voir la
[§13](#13-prereglages) pour les 23). Chaque champ de préréglage est surchargeable.

### Réglages d'étude

| Réglage | Signification |
|---|---|
| Technologie | ensemble de préréglages : fréquence, puissances, gains, sensibilité, hauteurs, meilleur modèle |
| Modèle | surcharge le modèle de propagation ([§14](#14-modeles)) |
| Environnement | selon le modèle : urbain/suburbain/ouvert (Hata), +métropolitain (COST-231), los/nlos (3GPP) |
| Fréquence | MHz ; les valeurs hors validité sont bornées avec un avertissement API explicite |
| Puissance TX / gain TX / gain RX / pertes | termes du bilan de liaison (dBm / dBi / dBi / dB) |
| Sensibilité RX | seuil du verdict de marge (dBm) |
| Marge d'évanouissement | dB supplémentaires soustraits avant le verdict — prévoir ~5,5 dB pour 90 % de confiance de zone, ~8 dB pour 95 % |
| Profondeur de feuillage | perte de végétation Weissberger (0–400 m) |
| Taux de pluie | affaiblissement dû à la pluie UIT-R P.838/P.530 (0–150 mm/h) |
| Encombrement %loc | encombrement statistique UIT-R P.2108 : 0 = désactivé, 50 = urbain médian, 90 = planification conservatrice (0,5–67 GHz ; dépend de la distance) |
| Modèle de surface | échantillonne un MNS (bâtiments/canopée comme obstacles) au lieu du terrain nu — affiché quand le serveur a `AM_DSM_URL` configuré |
| facteur k | courbure terrestre (0,1–10, défaut 4/3) |

### Ce que vous obtenez

- La **puissance reçue** par échantillon le long du trajet, répartition affaiblissement/diffraction.
- Le **verdict de ligne de visée** et le dégagement de la **première zone de Fresnel** (règle des 60 %).
- Le **pire obstacle** : emplacement, hauteur et ν de couteau de l'obstacle dominant, marqué sur le graphe.
- Le verdict de **marge vs sensibilité** pour la technologie choisie.
- La diffraction du terrain est toujours calculée par **Deygout multi-arêtes**
  (jusqu'à 3 arêtes, UIT-R P.526) sur le profil *fusionné* courbé par k — par-dessus le modèle empirique actif.

Les préréglages tenant compte du canal (LTE/5G/IoT privés) dérivent la
sensibilité du bruit thermique : `−174 + 10·log₁₀(BP) + FB + SINR`, et ajoutent
le gain MIMO au bilan. Avec l'encombrement activé, l'étude affiche une ligne
distincte **Encombrement (P.2108)** dans la décomposition des pertes (comme le
feuillage, la pluie et les gaz).

### Fiabilité de réfraction (faisceaux hertziens)

Chaque réponse de profil porte aussi un **contrôle de fiabilité à double k** sous
`rf.refraction` — le test hertzien standard selon lequel un bond fiable dégage
**100 % de la première zone de Fresnel à k = 4/3** (atmosphère standard) **et
60 % à k = 2/3** (sous-réfraction pire cas). Champs : `f1_ratio_k43`,
`f1_ratio_k23` et un booléen `reliable`. Un bond qui passe à 4/3 mais échoue à
2/3 tombera lors d'une propagation anormale.

### Optimiseur de hauteur d'antenne

`GET /api/terrain/optimize-heights` renvoie la **hauteur minimale TX et RX** (par
dichotomie, en maintenant l'autre extrémité fixe) qui atteint la ligne de visée
nue et la règle des 60 % de la première Fresnel — la question « quelle hauteur de
mât faut-il ? », résolue sans tâtonnement. `null` signifie que le critère est
inatteignable dans la limite de hauteur (défaut 120 m).

---

## 4a. Qualification par lot de récepteurs

Pour le fixe sans fil / WISP — qualifier de nombreuses adresses d'abonnés contre
un pylône — le panneau **Récepteurs par lot** (et `POST /api/rf/batch`) prend une
liste d'au plus 200 emplacements (`name,lat,lon` par ligne) et renvoie pour
chacun la distance, la puissance RX, la marge, le verdict de service, la ligne de
visée et le dégagement de Fresnel en un seul appel. Le panneau affiche un tableau
triable, colore servi/non-servi, permet de cliquer une ligne pour y déposer le RX,
et exporte l'ensemble en **CSV** (`?format=csv`) pour un CRM ou un tableur. Il
respecte les mêmes réglages feuillage / pluie / encombrement / MNS que l'étude de profil.

## 4b. Recherche du meilleur site

`POST /api/rf/site-search` classe une grille *n × n* de positions TX candidates
sur une boîte englobante (2×2 à 7×7) par fraction de zone servie grossière — la
question « où placer le mât ? ». Il utilise des balayages basse résolution pour
rester interactif ; relancez la coordonnée gagnante en couverture complète. Le
lot et la recherche de site sont des fonctions du niveau Pro en mode SaaS.

---

## 5. Simulation de couverture de zone

**Lancer la couverture** balaie une grille polaire vers l'extérieur depuis le TX
et peint une trame classée par marge sur la carte.

### Paramètres

| Réglage | Plage | Défaut | Notes |
|---|---|---|---|
| Rayon | 0,1–150 km | 10 | étendue de simulation |
| Radiales | 36–720 | 180 | résolution angulaire |
| Pas par radiale | 20–400 | 100 | résolution en distance |
| Taille de trame | 128–1 024 px | 512 | résolution de l'image de sortie |
| Antenne | omni / sectorielle / diagramme MSI importé | omni | voir la [§7](#7-antennes) |
| Azimut | 0–360° | — | pointage sectoriel/MSI |
| Ouverture H | 5–360° | 65 | secteur paramétrique (-3 dB) |
| Ouverture V | 1–90° | 10 | coupe verticale paramétrique |
| Dépointage bas | −10…+20° | 0 | tilt mécanique (le tilt électrique MSI est lu dans le fichier) |
| Marge d'évanouissement d'ombre | 0–30 dB | 0 | soustrait une provision d'évanouissement lognormal à chaque pixel — dimensionner pour 90/95 % de zone |
| Feuillage / pluie / encombrement / facteur k | comme en §4 | | appliqués par pas |
| Modèle de surface | on/off | off | nécessite `AM_DSM_URL` ; les bâtiments deviennent des obstacles |

### Sortie

- **Superposition raster** à 5 classes de marge (fort → marginal), transparente là où non servi ; légende incluse.
- **Fraction de zone servie**, pondérée par l'aire (correcte par anneau, pas par comptage de pixels).
- Statistiques de crête/bordure : altitude du sol au TX, puissance RX la plus forte, rayon.
- **Exports** : PNG (emprise géoréférencée), **GeoTIFF** (EPSG:4326, s'importe
  directement dans QGIS / ArcGIS / Atoll / Pathloss) et **KMZ** (superposition au sol Google Earth).

La diffraction du terrain par pas utilise le noyau vectorisé « arête dominante
unique », vérifié numériquement contre la référence float64 à < 0,05 dB. Un
balayage 10 km, 180×100 s'exécute en ~2–3 s avec un cache MNT chaud.

---

## 6. Cartes multisites « meilleur serveur »

Fonction du niveau Enterprise. Construisez une liste de sites et composez-les :

1. Configurez un TX (position, antenne, azimut, dépointage) et cliquez
   **Ajouter le TX actuel comme site** — répétez pour jusqu'à **8 sites**.
2. La **carte meilleur serveur** exécute une simulation de couverture complète
   par site et peint chaque pixel dans la couleur du site servant le plus fort
   (palette adaptée au daltonisme).
3. Les **parts meilleur serveur** par site et une fraction servie combinée sont
   affichées ; la trame est exportable comme la couverture monosite.

### Analyse SINR / interférence

Chaque exécution multisite (2 sites et plus) calcule aussi une **carte SINR
co-canal** : par pixel, `SINR = S / (I + N)` où S est le meilleur serveur, I la
somme linéaire de tous les autres sites entendus là (pire cas de réutilisation de
fréquence 1 — tous les sites sur la même porteuse) et N le plancher de bruit
thermique (`−174 + 10·log₁₀(BP) + FB`, tiré des paramètres de canal du préréglage
ou du `bandwidth_mhz` / `noise_figure_db` de la requête ; une valeur par défaut
10 MHz / 7 dB est utilisée — et signalée par un avertissement — si aucun n'est
disponible).

Le panneau gagne une bascule de vue **Meilleur serveur / SINR** plus trois
statistiques : SINR moyen sur la zone servie, % de zone à ≥ 6 dB (MCS
confortable) et la fraction de bord de cellule sous 0 dB. La trame SINR a sa
propre légende à 5 classes du vert à l'ambre et son URL PNG. Mettez
`interference: false` dans l'appel API pour la sauter.

Le multisite accepte les mêmes réglages physiques que le monosite (radiales
plafonnées à 360, pas à 200 par site ; trame jusqu'à 1 024 px sur la boîte
englobante de l'union).

---

## 7. Diagrammes d'antenne

Trois façons de modéliser l'antenne TX :

1. **Omni** (défaut) — gain appliqué uniformément.
2. **Secteur 3GPP paramétrique** — définissez azimut, ouverture horizontale
   (-3 dB), ouverture verticale et dépointage. Diagramme : `12·(Δ/BW)²` plafonné
   à 25 dB avant/arrière horizontalement et un plancher de 20 dB verticalement.
3. **Fichier MSI Planet mesuré** — importez un diagramme `.msi`/`.pln`/`.txt`
   (≤ 2 Mo). Le gain est converti dBd→dBi (+2,15) automatiquement ; le tilt
   électrique est lu dans l'en-tête ; l'atténuation est la somme des coupes H et V.
   Les diagrammes importés sont listés avec le gain et les ouvertures à -3 dB et
   sont privés à votre compte lorsque vous êtes connecté.

---

## 8. Studio intérieur et souterrain

Ouvrez **Intérieur / Souterrain** pour les trois onglets d'études qu'aucun outil
basé sur MNT ne peut exécuter. Fonction du niveau Pro en mode SaaS.

### Onglet 1 — Couverture plan d'étage / plan de mine

Utilise un DXF comme *structure*, pas comme relief — aucun géoréférencement
requis ; tout s'exécute en coordonnées de dessin.

1. Importez un plan d'étage (murs lus depuis LINE, LWPOLYLINE, POLYLINE, ARC/CIRCLE — arcs tessellés à 15°).
2. Assignez un **matériau par calque** — les noms de calques sont devinés
   automatiquement contre la bibliothèque de 12 matériaux
   ([§15](#15-materiaux)) ; marquez les calques décoratifs comme *Ignorer*.
3. Réglez l'**échelle d'unité** (mètres par unité de dessin), la fréquence (ou un
   préréglage), les hauteurs TX/RX (défaut 2,5 m / 1,2 m) et la résolution de
   grille (50–400 px, défaut 200).
4. **Multi-étages** (optionnel) : réglez *Étages traversés* (0–30) quand le TX se
   situe à N étages du plan cartographié. Le moteur ajoute le terme de
   pénétration d'étage COST-231 `Lf · n^((n+2)/(n+1) − 0,46)` — perte par dalle
   configurable (défaut 18,3 dB ≈ dalle béton), saturant avec n car l'énergie
   fuit de plus en plus par cages d'escalier/fenêtres — et étire la distance 3D
   par la hauteur d'étage. Le repli P.1238 respecte aussi le nombre d'étages.
5. **Cliquez sur le plan rendu** pour placer le TX — ou saisissez les X/Y exacts du plan.

Le moteur calcule le FSPL sur la distance 3D **plus la somme des traversées de
murs** (COST-231 multi-murs ; tests d'intersection de segments vectorisés exacts)
pour chaque cellule de grille, et compose une carte thermique avec les murs
dessinés par-dessus. Statistiques : % servi, plage dynamique de puissance RX. Si
**aucun mur** n'est trouvé sur les calques sélectionnés, il bascule
automatiquement sur la perte intérieure générale **UIT-R P.1238** et le signale
par un avertissement. Export : PNG de la carte thermique.

### Onglet 2 — Liaison tunnel / galerie de mine

Modèle de guide d'ondes Emslie — reproduit pourquoi l'UHF porte plus loin que la
VHF sous terre.

| Réglage | Plage | Défaut |
|---|---|---|
| Fréquence | > 0 MHz | 446 |
| Largeur / hauteur du tunnel | 0,5–30 m | 4 / 3 |
| Longueur | 10–50 000 m | 2 000 |
| Préréglage de paroi | béton, roche, charbon, calcaire, sel (εr 4–7) | roche |
| Polarisation | horizontale / verticale | horizontale |
| Rugosité | 0–1 m | 0,1 |
| Inclinaison | 0–10° | 0 |
| Puissance TX / gains / pertes / sensibilité | libre | 30 dBm / 6 dBi / 0 / 0 / −100 dBm |

Sortie : graphe puissance RX vs distance, atténuation en dB/m, le **point de
rupture** modal (avant lui le rayon direct domine ; après lui le mode guidé) et
la portée maximale vs sensibilité.

### Onglet 3 — À travers la terre (TTE)

Liaison boucle magnétique VLF à travers un sol conducteur (communications de
secours minières).

| Réglage | Plage | Défaut |
|---|---|---|
| Fréquence | 10 Hz–1 MHz | 5 000 Hz |
| Profondeur | 1–2 000 m | 100 |
| Préréglage de sol | roche sèche (0,001 S/m) → argile humide (0,1 S/m) | sol moyen (0,01) |
| Puissance TX / gain système / sensibilité | libre | 30 dBm / 20 dB / −130 dBm |

Sortie : **profondeur de peau**, répartition atténuation du sol vs étalement en
champ proche, perte totale, marge et verdict.

---

## 9. Lecture du graphe de profil

- **Remplissage du terrain** — bleu = échantillons SRTM, orange = échantillons
  DXF (la zone de fondu se nuance entre les deux). Les altitudes sont tracées sur
  la terre courbée par k.
- **Ligne verte** — ligne de visée TX→RX.
- **Ligne pointillée** — bord inférieur de la première zone de Fresnel ; un
  terrain la dépassant coûte une perte par diffraction même avec une visée
  optique dégagée.
- **Point rouge** — pire obstacle (ν de couteau le plus élevé).
- **Info-bulle** — par échantillon : altitude, source des données, hauteur de la
  ligne de visée, bord de Fresnel et (avec une technologie sélectionnée) la
  puissance reçue en dBm.
- Les graphes de plus de 512 échantillons sont sous-échantillonnés pour le rendu
  avec un algorithme préservant les crêtes (les crêtes d'obstacles ne sont jamais
  lissées) ; les exports contiennent toujours tous les échantillons.

---

## 10. Comptes, rôles et tableaux de bord

Les comptes sont optionnels en mode ouvert (voir `AM_SAAS_MODE` en
[§17](#17-configuration-serveur)). Connectez-vous depuis l'en-tête du
planificateur. L'inscription demande e-mail, mot de passe, organisation, **rôle**
et niveau de départ.

| Rôle | Tableau de bord | Conçu pour |
|---|---|---|
| **Manager** (IT Enterprise) | `/dashboard` — Centre de commande | CRUD de portefeuille de projets, KPI d'estimateur coût/ROI, gestion des plans, import de logo en marque blanche, **journal d'audit** de l'organisation |
| **Technicien de terrain** | `/field` — Vue tactique | thème sombre forcé, suivi GPS en direct avec contrôles d'altitude ponctuels, préréglages technologiques en un toucher qui amorcent le planificateur |
| **Avant-vente** | `/pitch` — Interface de présentation | comparaison de scénarios A/B avec tâches asynchrones + barres de progression, calculateur ROI (retour sur investissement, net à 5 ans), PDF exécutif |

Les trois renvoient au planificateur ; le rôle ne fait que choisir l'expérience
d'atterrissage par défaut — rien n'est verrouillé par rôle (les niveaux le font,
[§12](#12-niveaux)).

Propriétés de sécurité offertes d'emblée : mots de passe PBKDF2-SHA256 (200 000
itérations), jetons porteurs de 30 jours avec révocation à la déconnexion,
verrouillage de connexion (8 échecs / 15 min), propriété des ressources (vos DXF
et diagrammes d'antenne sont à vous), piste d'audit à portée d'organisation.

---

## 11. Projets, partage et rapports

### Projets

**Enregistrer comme projet** capture l'état complet du planificateur (points,
réglages d'étude, référence DXF, sites) dans un espace de travail nommé. Depuis
le tableau de bord (ou l'API) vous pouvez lister, renommer, dupliquer et
supprimer des projets ; ouvrir `/?project=ID` en restaure un à l'identique.
Quotas par niveau : 3 / 25 / illimité.

### Partage

**Partager** crée une URL à jeton public en lecture seule pour un projet (le
jeton est retiré des réponses pour tout autre que le propriétaire). Quiconque
possède le lien peut consulter — révoquez en supprimant le projet.

### Rapports PDF

`POST /api/saas/report.pdf` (ou le bouton *PDF exécutif* du tableau de bord
Présentation) génère un rapport de marque : matrice du bilan de liaison (avec les
lignes de pertes environnementales), le graphe de profil du terrain, la trame de
couverture et une nomenclature CAPEX/OPEX/TCO à 5 ans. Les comptes Enterprise
avec un logo importé (PNG/JPEG ≤ 1 Mo) obtiennent une image de marque en
**marque blanche**.

### Estimateur de coûts et nomenclature matérielle (BOM)

`GET /api/saas/costs?technology=…&sites=…` — nomenclature par technologie (radio,
antenne, installation, licences…) avec CAPEX, OPEX annuel et TCO à 5 ans,
utilisée par les vues ROI du tableau de bord et de la présentation. Le lien
**Nomenclature (CSV)** du Centre de commande (`GET /api/saas/bom.csv`) télécharge
la même nomenclature avec des lignes proportionnées à la flotte, plus des lignes
de synthèse CAPEX/OPEX/TCO — le livrable d'approvisionnement pour un bon de commande.

### Usage terrain et hors ligne (PWA)

AntennaMaster est une application web progressive installable. Un service worker
met en cache la coquille de l'application, chaque tuile de carte consultée et vos
derniers résultats d'API, afin que l'outil continue de fonctionner **hors réseau**
— l'exigence décisive pour les sites à ciel ouvert, souterrains et du dernier
kilomètre distant. La **Vue tactique** (`/field`) affiche un indicateur **en
ligne / hors ligne** en direct ; hors ligne, elle bascule sur les tuiles et
résultats en cache. Ajoutez-la à l'écran d'accueil d'un téléphone via le menu
« Installer l'application » / « Ajouter à l'écran d'accueil » du navigateur. (Le
service worker ne s'active qu'en builds de production.)

### Tâches asynchrones

Les longues simulations peuvent s'exécuter en tâches de fond
(`POST /api/saas/coverage/async` → `GET /api/saas/jobs/{id}` avec un % de
progression en direct). Au plus **4 tâches** s'exécutent simultanément ; une 5e
renvoie HTTP 429 — réessayez après la fin de l'une d'elles.

---

## 12. Niveaux d'abonnement

| | **Basic** 0 $/mois | **Pro** 79 $/mois | **Enterprise** 299 $/mois |
|---|---|---|---|
| Terrain SRTM global, tous fournisseurs de carte | ✓ | ✓ | ✓ |
| Préréglages grand public (Wi-Fi, PMR, diffusion, cellulaire, IoT) | ✓ | ✓ | ✓ |
| Projets enregistrés | 3 | 25 | illimité |
| **Fusion de terrain DXF** | — | ✓ | ✓ |
| **Préréglage faisceau PtP (18 GHz)** avec pluie et gaz | — | ✓ | ✓ |
| **Studio intérieur / souterrain** | — | ✓ | ✓ |
| **Rapports PDF** | — | ✓ | ✓ (marque blanche) |
| **Préréglages LTE B48 / NR n77 / LTE-M privés** | — | — | ✓ |
| **Meilleur serveur multisite** | — | — | ✓ |
| **Jetons API** | — | — | ✓ |

Clés de fonctionnalités (pour l'API) : `srtm_terrain`, `wifi_presets` → basic ;
`dxf_fusion`, `ptp_backhaul`, `pdf_export`, `indoor_studio` → pro ;
`private_networks`, `multi_site`, `api_access`, `white_label` → enterprise.

En **mode ouvert** (défaut, `AM_SAAS_MODE` non défini) rien n'est verrouillé et
aucun compte n'est requis. En **mode SaaS**, un appel verrouillé sans le bon
niveau renvoie HTTP **402** avec le nom de la fonction et le niveau requis. Les
changements de niveau sont appliqués par un webhook de facturation
(`POST /api/auth/tier` avec `X-Billing-Secret`), pas par l'utilisateur directement.

---

## 13. Référence : préréglages technologiques

Tous les champs sont surchargeables par étude. Les opérateurs peuvent fusionner
des plans de bande supplémentaires depuis `DATA_DIR/technologies.json` sans
modification de code (les nouvelles clés doivent porter l'ensemble complet des champs).

| Clé | Préréglage | MHz | Modèle par défaut | Env | TX dBm | GTX dBi | GRX dBi | Pertes dB | Sens dBm | h TX / h RX (m) |
|---|---|---|---|---|---|---|---|---|---|---|
| `gsm900` | GSM 900 (2G) | 945 | Okumura-Hata | suburbain | 43 | 15 | 0 | 3 | −102 | 30 / 1,5 |
| `gsm1800` | GSM 1800/DCS (2G) | 1842 | COST-231 | urbain | 43 | 17 | 0 | 3 | −102 | 30 / 1,5 |
| `umts900` | UMTS 900 (3G) | 942,5 | Okumura-Hata | suburbain | 43 | 15 | 0 | 3 | −117 | 30 / 1,5 |
| `umts2100` | UMTS 2100 (3G) | 2140 | 38.901 UMa | nlos | 43 | 18 | 0 | 3 | −117 | 30 / 1,5 |
| `lte800` | LTE 800/B20 (4G) | 806 | Okumura-Hata | suburbain | 46 | 15 | 0 | 3 | −105 | 30 / 1,5 |
| `lte1800` | LTE 1800/B3 (4G) | 1842,5 | COST-231 | urbain | 46 | 17 | 0 | 3 | −103 | 30 / 1,5 |
| `lte2600` | LTE 2600/B7 (4G) | 2655 | 38.901 UMa | nlos | 46 | 18 | 0 | 3 | −100 | 30 / 1,5 |
| `nr700` | 5G NR n28 700 MHz | 758 | Okumura-Hata | suburbain | 46 | 15 | 0 | 3 | −105 | 30 / 1,5 |
| `nr3500` | 5G NR n78 3,5 GHz | 3550 | 38.901 UMa | nlos | 49 | 24 | 0 | 3 | −100 | 25 / 1,5 |
| `nr28000` | 5G NR n257 28 GHz mmWave | 28000 | 38.901 UMi | nlos | 40 | 30 | 10 | 2 | −95 | 10 / 1,5 |
| `pmr446` | PMR446 portatif | 446,1 | Okumura-Hata | ouvert | 27 | 0 | 0 | 0 | −119 | 30 / 1,5 |
| `tetra400` | TETRA 400 (PPDR) | 420 | Okumura-Hata | suburbain | 44 | 9 | 0 | 2 | −112 | 40 / 1,5 |
| `vhf150` | VHF mobile terrestre 150 | 155 | Okumura-Hata | ouvert | 44 | 3 | 0 | 1,5 | −116 | 40 / 1,5 |
| `fm100` | Diffusion FM 87–108 | 100 | FSPL | ouvert | 60 | 6 | 0 | 1,5 | −90 | 100 / 10 |
| `dvbt600` | DVB-T/T2 UHF 600 | 600 | Okumura-Hata | ouvert | 63 | 10 | 12 | 3 | −84 | 150 / 10 |
| `wifi2400` | Wi-Fi 2,4 GHz extérieur | 2442 | 38.901 UMi | nlos | 20 | 8 | 2 | 1 | −82 | 10 / 1,5 |
| `wifi5800` | Wi-Fi 5,8 GHz PtMP | 5800 | 38.901 UMi | los | 23 | 16 | 14 | 1 | −80 | 20 / 5 |
| `lora868` | LoRaWAN 868 (IoT) | 868 | Okumura-Hata | suburbain | 14 | 3 | 0 | 0,5 | −137 | 25 / 1,5 |
| `ptp18000` † | Faisceau PtP 18 GHz | 18000 | FSPL | los | 20 | 38 | 38 | 2 | −70 | 30 / 30 |
| `private_lte_b48` ‡ | LTE B48/CBRS privé | 3625 | 38.901 UMa | nlos | 40 | 15 | 0 | 1 | −102 * | 15 / 1,5 |
| `private_nr_n77` ‡ | 5G NR n77 100 MHz privé | 3900 | 38.901 UMa | nlos | 47 | 24 | 0 | 1 | −95 * | 15 / 1,5 |
| `private_lte_iot` ‡ | LTE-M/NB-IoT 1,4 MHz privé | 3625 | 38.901 UMa | nlos | 40 | 15 | 0 | 1 | −120 * | 15 / 1,5 |
| `custom` | Étude personnalisée | 446 | FSPL | ouvert | 30 | 0 | 0 | 0 | −100 | 20 / 1,5 |

† Niveau Pro en mode SaaS · ‡ Niveau Enterprise en mode SaaS ·
\* tenant compte du canal : sensibilité recalculée depuis la largeur de bande
(20 / 100 / 1,4 MHz), le facteur de bruit (7 dB) et le SINR cible (−3 / −3 / −6 dB) ;
gain MIMO (3 / 6 / 0 dB) ajouté au bilan.

---

## 14. Référence : modèles de propagation

| Clé | Modèle | Fréquence valide | Environnements | Usage typique |
|---|---|---|---|---|
| `fspl` | Espace libre (UIT-R P.525) | 1 MHz–300 GHz | — | référence, faisceau PtP |
| `okumura_hata` | Okumura-Hata | 150–1 500 MHz | urbain, suburbain, ouvert | GSM900, TETRA, PMR, FM/TV |
| `cost231_hata` | COST-231 Hata | 1 500–2 000 MHz | urbain, métropolitain, suburbain, ouvert | GSM1800/DCS, UMTS2100 |
| `tr38901_rma` | 3GPP TR 38.901 RMa | 0,5–30 GHz | los, nlos | macro rural 4G/5G |
| `tr38901_uma` | 3GPP TR 38.901 UMa | 0,5–100 GHz | los, nlos | macro urbain LTE / 5G |
| `tr38901_umi` | 3GPP TR 38.901 UMi | 0,5–100 GHz | los, nlos | petites cellules, mmWave de rue |

Tous les modèles sont bornés par le bas par le FSPL. Les entrées hors validité
sont bornées et un avertissement est joint à la réponse. La **diffraction du
terrain Deygout multi-arêtes** (≤ 3 arêtes, UIT-R P.526) est toujours ajoutée
par-dessus, calculée sur le profil fusionné courbé par k.

Compléments environnementaux (tout modèle) : feuillage Weissberger (0–400 m),
affaiblissement dû à la pluie UIT-R P.838-3/P.530 (atténuation spécifique ×
longueur de trajet effective), absorption gazeuse de type UIT-R P.676 (raies de
l'oxygène à 60 GHz / de la vapeur d'eau à 22 GHz — automatique, significative
seulement pour les PtP haute fréquence), et **encombrement statistique UIT-R
P.2108 §3.2** — la perte d'occupation du sol d'origine humaine que le MNT ne peut
voir, à un pourcentage réglable d'emplacements (50 = médian, 90 = conservateur ;
défini de 0,5 à 67 GHz, les requêtes sous 500 MHz utilisent la courbe 0,5 GHz
avec un avertissement).

Modèles intérieur/souterrain : COST-231 multi-murs, UIT-R P.1238, guide d'ondes
de tunnel Emslie, profondeur de peau TTE — voir la [§8](#8-interieur-souterrain).

---

## 15. Référence : matériaux et préréglages

### Matériaux de murs (dB par traversée, interpolés en log-fréquence)

| Matériau | 900 MHz | 2,4 GHz | 5,8 GHz |
|---|---|---|---|
| Cloison sèche / plaque de plâtre | 2 | 3 | 4 |
| Bois / porte | 3 | 4 | 6 |
| Verre (ordinaire) | 1,5 | 2 | 3 |
| Verre (traité faible émissivité) | 10 | 12 | 15 |
| Mur en brique | 6 | 8 | 12 |
| Béton 20 cm | 10 | 13 | 20 |
| Béton armé 30 cm+ | 18 | 23 | 32 |
| Métal / blindage | 26 | 30 | 35 |
| Pilier rocheux (mine) | 25 | 35 | 45 |
| Terre / remblai | 30 | 45 | 60 |
| Ascenseur / machinerie | 20 | 25 | 30 |
| Ignorer (calque décoratif) | 0 | 0 | 0 |

### Préréglages de parois de tunnel (permittivité relative εr)

béton 6,0 · roche dure (granite) 5,0 · charbon 4,0 · calcaire 7,0 · sel 4,5

### Préréglages de conductivité du sol (S/m)

roche sèche/granite 0,001 · calcaire (karst) 0,005 · sol moyen 0,01 ·
veines de charbon 0,02 · sol humide/argile 0,1

---

## 16. Référence : chaque réglage

Liste consolidée de chaque paramètre ajustable avec sa plage valide.

### Trajet et profil (`GET /api/terrain/profile`, barre latérale du planificateur)

| Paramètre | Plage | Défaut |
|---|---|---|
| lat, lon TX/RX | ±90 / ±180 | — |
| Hauteur TX / RX (m/sol) | ≥ 0 | 20 / 10 |
| Échantillons | 16–2 048 | 256 |
| facteur k | 0,1–10 | 4/3 |
| technology / model / environment | voir §13–14 | — |
| freq_mhz | > 0 | préréglage (sinon 446) |
| tx_power_dbm, tx_gain_dbi, rx_gain_dbi, losses_db, rx_sensitivity_dbm | libre | préréglage |
| foliage_depth_m | 0–400 | 0 |
| rain_rate_mm_h | 0–150 | 0 |
| clutter_pct | 0–99,9 (0 = désactivé) | 0 |
| surface | true/false (nécessite `AM_DSM_URL`) | false |
| dxf_id | DXF géoréférencé | aucun (SRTM seul) |

### Couverture (`POST /api/rf/coverage`)

| Paramètre | Plage | Défaut |
|---|---|---|
| radius_km | 0,1–150 | 10 |
| n_radials | 36–720 | 180 |
| n_steps | 20–400 | 100 |
| raster_px | 128–1 024 | 512 |
| antenna_azimuth_deg | 0–360 | omni |
| antenna_beamwidth_deg | 5–360 | 65 |
| vertical_beamwidth_deg | 1–90 | 10 |
| downtilt_deg | −10–+20 | 0 |
| antenna_id | id MSI importé | — |
| shadow_margin_db | 0–30 | 0 |
| k_factor | 0,1–10 | 4/3 |
| foliage_depth_m / rain_rate_mm_h | 0–400 / 0–150 | 0 / 0 |
| clutter_pct | 0–99,9 | 0 |
| surface | true/false | false |
| + toutes les surcharges de bilan de liaison de la §4 | | |

### Multisite (`POST /api/rf/coverage/multi`)

Comme la couverture, sauf : `sites` 1–8 (chacun avec lat/lon, azimut,
dépointage, antenne optionnelle), `n_radials` 36–360 (défaut 120), `n_steps`
20–200 (défaut 80), `raster_px` défaut 768. Analyse SINR : `interference` (défaut
true), `bandwidth_mhz` (0–400, sinon préréglage/10), `noise_figure_db` (0–20,
sinon préréglage/7).

### Récepteurs par lot (`POST /api/rf/batch`)

`lat`/`lon` (TX), `receivers` 1–200 (chacun `lat`, `lon`, `name` optionnel,
`rx_height_m`), `technology`, `dxf_id`, `surface`, `k_factor`, `foliage_depth_m`,
`rain_rate_mm_h`, `clutter_pct`, et les mêmes surcharges de bilan que la
couverture. `?format=csv` pour un téléchargement CSV.

### Recherche du meilleur site (`POST /api/rf/site-search`)

Boîte `south`/`west`/`north`/`east`, `grid_n` 2–7 (défaut 5), `technology`,
`radius_km` 0,1–50, `shadow_margin_db`, `clutter_pct`, `k_factor`, `dxf_id`,
`surface`, et surcharges de bilan côté TX.

### Optimiseur de hauteur (`GET /api/terrain/optimize-heights`)

`lat1`/`lon1`/`lat2`/`lon2`, `tx_height_m`, `rx_height_m`, `freq_mhz` ou
`technology`, `k_factor`, `max_height_m` (1–500, défaut 120), `dxf_id`, `surface`.

### Couverture intérieure (`POST /api/indoor/coverage`)

| Paramètre | Plage | Défaut |
|---|---|---|
| unit_scale (m par unité de dessin) | > 0 | 1 |
| correspondance calque→matériau | §15 | devinée |
| tx_x, tx_y (coords de dessin) | dans le plan | clic |
| tx_height_m / rx_height_m | > 0 | 2,5 / 1,2 |
| floors_crossed | 0–30 | 0 |
| floor_height_m | 2–6 | 3 |
| floor_loss_db | 0–40 | 18,3 |
| grid_px | 50–400 | 200 |
| freq_mhz ou technology | > 0 | préréglage |
| tx_power_dbm etc. | libre | préréglage |

### Tunnel (`GET /api/indoor/tunnel`)

freq > 0 (446) · largeur 0,5–30 m (4) · hauteur 0,5–30 m (3) ·
longueur 10–50 000 m (2 000) · préréglage de paroi (roche) · polarisation h/v ·
rugosité 0–1 m (0,1) · inclinaison 0–10° (0) · termes de bilan libres.

### TTE (`GET /api/indoor/tte`)

freq 10 Hz–1 MHz (5 000) · profondeur 1–2 000 m (100) · préréglage de sol
(average_soil) · tx_power_dbm (30) · system_gain_db (20) · rx_sensitivity_dbm (−130).

### Géoréférencement (`POST /api/dxf/{id}/georeference`)

mode `known_crs` (chaîne epsg/proj) | `control_points` (2–3 paires) |
`origin_bearing` (lat, lon, azimut 0–360, échelle d'unité, décalages) ·
z_scale libre (défaut suit l'horizontale) · sélection de calques.

### Réglages d'interface uniquement

Fond de carte + URL XYZ personnalisée · thème (auto/sombre/clair) · marge
d'évanouissement · recherche · GPS · inverser les extrémités · liste des sites ·
enregistrement/chargement de projet.

---

## 17. Configuration serveur (variables d'environnement)

Tout le comportement du backend est réglable via des variables d'environnement
`AM_*` — aucune modification de code nécessaire.

| Variable | Défaut | Rôle |
|---|---|---|
| `AM_DATA_DIR` | `backend/data` | racine du cache MNT, du stock DXF, des résultats, de la base SQLite |
| `AM_DEM_URL` | gabarit AWS Terrarium | toute source d'altitude XYZ encodée en Terrarium |
| `AM_DEM_ZOOM` | 12 (≈ 38 m/px) | zoom des tuiles MNT ; plus élevé = plus fin + plus de tuiles |
| `AM_DSM_URL` | non défini | source optionnelle de **modèle de surface** encodée en Terrarium (bâtiments/canopée) ; active `surface=true` sur les profils et la couverture |
| `AM_BASEMAP_URL` | OSM | source du serveur de tuiles de fond de carte local (`/api/basemap`) utilisé pour les cartes hors ligne |
| `AM_DEM_CACHE_MB` | 2048 | budget disque du cache de tuiles (éviction LRU) |
| `AM_FEATHER_CELLS` | 3.0 | largeur de la bande de fondu DXF↔SRTM, en cellules de grille |
| `AM_VALIDATION_DIFF_M` | 50.0 | écart d'altitude moyenne déclenchant l'avertissement strict |
| `AM_MAX_DXF_MB` | 100 | limite d'import DXF |
| `AM_CORS_ORIGINS` | `*` | origines autorisées séparées par des virgules |
| `AM_SAAS_MODE` | non défini (ouvert) | `1` = impose comptes, niveaux et quotas |
| `AM_BILLING_SECRET` | non défini | secret partagé requis par le webhook de changement de niveau en mode SaaS |

Frontend : `BACKEND_URL` (défaut `http://localhost:8010`) — où le serveur Next.js
proxifie `/api/*`.

Plans de bande d'opérateur : déposez un `technologies.json` dans `AM_DATA_DIR`
pour fusionner des préréglages personnalisés (chaque nouvelle clé nécessite
l'ensemble complet des champs ; les clés existantes ne sont jamais écrasées).

---

## 18. Limites et capacités

| Ressource | Limite |
|---|---|
| Import DXF | 100 Mo (configurable) |
| Fichier d'antenne MSI | 2 Mo |
| Logo marque blanche | 1 Mo (PNG/JPEG) |
| Grille de terrain DXF | ≤ 400×400 cellules |
| Échantillons de profil | ≤ 2 048 |
| Balayage de couverture | ≤ 720 radiales × 400 pas, ≤ 150 km de rayon |
| Trame de couverture | ≤ 1 024 px |
| Sites par composite | 8 |
| Grille intérieure | ≤ 400 px |
| Tâches asynchrones simultanées | 4 (429 au-delà) |
| Résultats raster stockés | 200 derniers (disque, purge auto ; tout worker sert tout résultat) |
| Cache RAM MNT | 2 000 tuiles décodées |
| Projets enregistrés | 3 / 25 / ∞ selon le niveau |
| Jetons de session | TTL 30 jours, révoqués à la déconnexion |
| Verrouillage de connexion | 8 échecs / 15 minutes |
| Seuils de benchmark (CI) | chaque scénario de point d'accès < 5 s, < 1 Go — voir `QA_BENCHMARK_REPORT.md` |

Vérifié par 100 cas de test backend + 10 tests frontend (`./start.sh --check`).

## 19. Dépannage

| Symptôme | Cause et remède |
|---|---|
| Avertissement *« l'altitude DXF moyenne diffère du SRTM de X m »* | presque toujours une confusion pieds/mètres (réglez l'échelle d'unité / `z_scale` 0,3048) ou un code EPSG erroné — vérifiez les résidus Helmert |
| Grands résidus Helmert (m) | un point de calage est mal identifié ; re-sélectionnez-le |
| HTTP **402** sur un point d'accès | la fonction est verrouillée par niveau en mode SaaS — la réponse indique quel niveau la débloque |
| HTTP **429** sur couverture asynchrone | 4 tâches déjà en cours ; attendez et réessayez |
| HTTP **429** à la connexion | verrouillage après 8 tentatives échouées — attendez 15 min |
| HTTP **502** des points terrain | source de tuiles MNT inaccessible — vérifiez Internet / `AM_DEM_URL` |
| La recherche de lieu ne fait rien | le géocodage Nominatim nécessite Internet ; la saisie `lat, lon` fonctionne toujours hors ligne |
| La couverture paraît trop optimiste | ajoutez une marge d'évanouissement d'ombre (5,5 dB ≈ 90 %, 8 dB ≈ 95 % de zone), activez l'encombrement P.2108 pour les zones bâties, et vérifiez le réglage d'environnement (nlos vs los) |
| 422 « No surface model configured » | `surface=true` nécessite `AM_DSM_URL` pointant vers une source de tuiles MNS encodée en Terrarium |
| Avertissement SINR sur récepteur supposé | le préréglage n'a pas de paramètres de canal — passez `bandwidth_mhz` / `noise_figure_db` dans la requête multisite |
| La carte thermique intérieure ignore les murs | les calques sélectionnés n'avaient pas d'entités ligne — l'avertissement de repli P.1238 vous le dit ; vérifiez la sélection de calques et la correspondance de matériaux |
| Le graphe de profil paraît plat sous la ligne de visée | vous êtes peut-être zoomé sur un long trajet — survolez le point du pire obstacle ; le graphe est courbé par k, le terrain descend avec la distance |
| Avertissement du modèle sur la fréquence | vous êtes hors de la plage de validité du modèle — la valeur a été bornée ; choisissez un modèle adapté en §14 |

Frontières de modélisation connues (par conception, documentées dans
`docs/CAPABILITIES.md`) : modèles empiriques médians + diffraction par couteau
(pas d'ITM/P.1546/P.452 — Deygout + la famille Hata/38.901 couvre les mêmes cas
d'usage de planification) ; l'encombrement est statistique (UIT-R P.2108), pas une
base d'occupation du sol par pixel ; le SINR suppose le pire cas de réutilisation
co-canal 1 (pas de plan de fréquences / ordonnanceur) ; le multi-étages est un
terme de pénétration, pas des cartes de murs par étage ; l'obstruction par
bâtiment nécessite une source de tuiles MNS fournie par l'utilisateur (`AM_DSM_URL`).

---

## 20. Modules avancés, jumeau numérique 3D et opérations en direct

Au-delà de la prédiction de couverture, AntennaMaster *conçoit*, *certifie* et
*exploite* désormais. Ouvrez **Études avancées** depuis le planificateur pour les
outils au niveau liaison ; la vue 3D, les Opérations en direct et le LiDAR sont
décrits ci-dessous. Référence complète des points d'accès :
`VISION_ARCHITECTURE.md` et la page OpenAPI.

### Phonie bidirectionnelle « talk-back » (radio mobile terrestre)

Un système radio est limité par la *plus faible* des deux directions. L'outil
bidirectionnel calcule la **voie descendante** (base → portatif) *et* la **voie
montante** (portatif → base), note chacune en **DAQ** (qualité audio délivrée,
TIA-4046) et indique la direction limitante et la zone de phonie fiable. Il
modélise la **perte du corps** du portatif et une **classe de pénétration** (dans
la rue / en véhicule / en bâtiment / en sous-sol), et un solveur de **cascade de
répéteurs** renvoie l'espacement et le nombre pour une couverture continue de corridor.

| Point d'accès | Rôle |
|---|---|
| `POST /api/rf/twoway/link` | verdict de liaison bidirectionnel (descendant/montant, DAQ, direction limitante) |
| `POST /api/rf/twoway/coverage` | étude de zone : fractions servies descendant / montant / fiable des deux |
| `POST /api/rf/twoway/repeater-cascade` | nombre et espacement de répéteurs pour un corridor |

### Câble rayonnant et antennes distribuées (métro / mine)

La vraie manière de couvrir les tunnels — un **câble coaxial rayonnant (leaky
feeder)** ou un **système d'antennes distribuées**. L'outil modélise la perte
longitudinale + de couplage du câble, résout l'**espacement des amplificateurs en
ligne**, ajoute la perte de courbure, et rapporte la longueur servie et le pire
trou non couvert ; le concepteur DAS transforme la portée d'une antenne unique
Emslie en nombre et espacement d'antennes.
`POST /api/indoor/leaky-feeder` · `GET /api/indoor/tunnel-das`.

### Placement automatique des points d'accès (campus / entrepôt)

L'inverse de la carte thermique : étant donné un plan d'étage et un objectif de
couverture (et de capacité optionnel), `POST /api/indoor/auto-place` renvoie
**combien** de points d'accès, **où**, et sur **quel canal** — placement glouton
à couverture maximale sur le même moteur multi-murs, un plan de canaux par
coloration de graphe (2,4 / 5 / 6 GHz), un plancher de capacité utilisateurs ×
débit et un contrôle de recouvrement de roaming à −67 dBm.

### Conformité d'exposition RF / CEM

`POST /api/rf/compliance` calcule les distances de zones d'exclusion **ICNIRP**
ou **FCC OET-65** pour le public et les professionnels, ainsi que le ratio
d'exposition à une distance donnée — le préalable au permis avant la mise sous
tension d'une antenne.

### Longley-Rice (ITM) avec quantile de fiabilité

`GET /api/terrain/itm` ajoute un affaiblissement par **modèle de terrain
irrégulier** qui fournit un *quantile de fiabilité* (fraction de temps et de
situations), et non seulement une médiane — le modèle statistique qui manque aux
courbes empiriques. Il combine la diffraction Deygout validée avec la statistique
de rugosité du terrain Longley-Rice et la variabilité temps/situation de l'ITM.

### Calibration par mesures terrain (drive test)

`POST /api/rf/calibrate` ajuste une correction de décalage (et de pente en
distance optionnelle) à partir de **RSSI mesurés** face à la prédiction et
rapporte l'erreur RMS avant et après — transformant les prédictions en
prédictions calibrées et fiables pour le site.

### Copilote de conception IA

`POST /api/copilot/analyze/link` exécute le profil **et** l'optimiseur de
hauteur, puis explique le résultat sous forme de constats classés et actionnables
avec un **correctif chiffré** (surélever le mât à X m, ajouter Y dB, changer de
bande, ajouter un répéteur). Il est déterministe et fonctionne hors ligne ; un
narrateur Claude optionnel ajoute de la prose lorsqu'une clé API est présente.
`GET /api/copilot/tools` publie un catalogue d'outils lisible par machine pour
qu'un agent externe pilote le simulateur.

### Jumeau numérique 3D (CesiumJS)

Une bascule **2D / 3D** transparente sur la carte affiche le terrain fusionné
SRTM+DXF dans un globe WebGL — alimenté par les tuiles d'élévation propres à la
plateforme (`GET /api/terrain/heightmap/{z}/{x}/{y}.bin`, sans clé Cesium Ion,
utilisable hors ligne). Elle dessine un **tube de Fresnel** 3D lumineux le long de
la ligne de visée réelle, des marqueurs rouges là où le terrain pénètre la zone de
Fresnel, et drape la carte thermique de couverture sur le relief 3D.

### Opérations en direct (télémétrie du jumeau numérique)

Le tableau de bord **Opérations en direct** (`/live`) ingère les positions
d'actifs en temps réel depuis des flux de gestion de flotte ou IoT
(`POST /api/telemetry/ingest`, WebSocket `/api/telemetry/ws`) et diffuse le
jumeau en direct via Server-Sent Events (`/api/telemetry/stream`). Chaque actif
est corrélé à la prédiction RF : il clignote en **jaune** à l'entrée d'une **zone
morte** prédite, et un événement de **déconnexion RF** est journalisé (avec la
mention si la dernière position était en zone morte) lorsqu'il cesse d'émettre.
Liez la prédiction avec `POST /api/telemetry/coverage-context`.

### Ingestion LiDAR drone / nuage de points

`POST /api/lidar/upload` ingère un relevé `.las`/`.laz` et le rastérise en un
**modèle numérique de surface (MNS)** qui remplace l'encombrement statistique,
afin que la diffraction soit calculée contre les **vrais bâtiments, arbres et
engins relevés**. `GET /api/lidar/{id}/profile` renvoie une comparaison
surface-relevée vs terrain-nu (validé : un bâtiment de 50 m a fait passer la
diffraction modélisée d'une liaison de 40 dB à 114 dB).
