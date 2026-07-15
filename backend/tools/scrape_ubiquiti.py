#!/usr/bin/env python3
"""Scrape Ubiquiti's official techspecs site into a catalog source file.

    python -m tools.scrape_ubiquiti            # writes catalog_sources/ubiquiti.json
    python -m tools.scrape_ubiquiti --limit 5  # bounded test run

techspecs.ui.com is a Next.js site whose per-product JSON
(`/_next/data/<buildId>/<line>/<category>/<slug>.json`) carries the full
structured specification the vendor publishes — antenna gain per band,
conducted TX power, operating frequency, and a link to the official
datasheet PDF.  Values are copied verbatim (worst-case reduction only:
max gain across bands, max conducted TX).  Records carry
``spec_confidence: "datasheet"`` and the exact source URL; products whose
JSON exposes no RF spec are skipped, never guessed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "data" / "catalog_sources" / "ubiquiti.json"
BASE = "https://techspecs.ui.com"

# (product line, category, default equipment_class or None = classify by gain)
CATEGORIES = [
    ("unifi", "wifi", "wifi_ap"),
    ("uisp", "wireless", None),
    ("uisp", "60ghz-wireless", "mmwave_ptp"),
]

BAND_MHZ = {
    "2-4-ghz": [2400, 2500], "5-ghz": [5150, 5875], "6-ghz": [5925, 7125],
    "60-ghz": [57000, 66000], "900-mhz": [902, 928], "24-ghz": [24000, 24250],
}

UA = {"User-Agent": "AntennaMaster-catalog/1.0 (RF planning; spec ingestion)"}


def get(url: str, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def build_id() -> str:
    html = get(BASE).decode("utf-8", errors="replace")
    m = re.search(r'"buildId":\s*"([^"]+)"', html)
    if not m:
        raise RuntimeError("buildId not found on techspecs.ui.com")
    return m.group(1)


def spec_entries(obj) -> list[tuple[str, str]]:
    """Every (feature slug, value) pair anywhere in the product JSON."""
    out: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        tn = obj.get("__typename", "")
        if tn.startswith("SpecificationEntitySectionFeatureEntry"):
            slug = (obj.get("feature") or {}).get("slug")
            val = obj.get("value")
            if slug and isinstance(val, str):
                out.append((slug, val))
        for v in obj.values():
            out.extend(spec_entries(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(spec_entries(v))
    return out


def datasheet_rows(p: dict) -> dict[str, str]:
    """Older products publish the spec table as datasheet.html — parse the
    key/value rows verbatim."""
    html = (p.get("datasheet") or {}).get("html") if isinstance(
        p.get("datasheet"), dict) else None
    if not html:
        return {}
    out: dict[str, str] = {}
    for m in re.finditer(
            r'(?is)<td class="key">(.*?)</td>\s*<td class="value">(.*?)</td>',
            html):
        k = re.sub(r"<[^>]+>", " ", m.group(1))
        v = re.sub(r"<br\s*/?>", "\n", m.group(2))
        v = re.sub(r"<[^>]+>", " ", v)
        k = re.sub(r"\s+", " ", k).strip().rstrip("*").strip()
        v = re.sub(r"[ \t]+", " ", v).strip()
        if k and v:
            out[k] = v
    return out


def _conducted_dbm(text: str) -> float | None:
    """Max conducted TX power: 'NN dBm' figures not annotated as EIRP."""
    vals = [float(m.group(1)) for m in
            re.finditer(r"(-?\d+(?:\.\d+)?)\s*dBm(?!\s*EIRP)", text)
            if "EIRP" not in text[m.end():m.end() + 8]]
    return max(vals) if vals else None


def to_record(line: str, cat: str, slug: str, data: dict,
              default_cls: str | None) -> dict | None:
    p = (data.get("pageProps") or {}).get("product") or {}
    if not p:
        return None
    specs = dict(spec_entries(p))

    gains: dict[str, float] = {}
    beam = None
    for k, v in specs.items():
        m = re.match(r"(?:antenna-)?gain(?:-(.+))?$", k)
        if not m:
            continue
        dbi = [float(x) for x in
               re.findall(r"(?<![\d.-])(\d+(?:\.\d+)?)\s*dBi", v)]
        if dbi:
            gains[m.group(1) or "unbanded"] = max(dbi)
        bm = re.search(r"(\d+(?:\.\d+)?)\s*°\s*x\s*(\d+(?:\.\d+)?)\s*°", v)
        if bm and beam is None:
            beam = float(bm.group(1))
    for k, v in specs.items():          # passive antennas: beamwidth rows
        if beam is None and "beamwidth" in k:
            bm = re.search(r"(\d+(?:\.\d+)?)\s*°", v)
            if bm:
                beam = float(bm.group(1))

    tx_vals = [d for k, v in specs.items()
               if ("tx-power" in k or k == "transmit-power")
               and (d := _conducted_dbm(v)) is not None]

    # Fallback for older products: the official spec table in datasheet.html.
    ds_bands: list[list[float]] = []
    if not gains and not tx_vals:
        rows = datasheet_rows(p)
        for k, v in rows.items():
            kl = k.lower()
            if "tx power" in kl or "output power" in kl:
                d = _conducted_dbm(v)
                if d is not None:
                    tx_vals.append(d)
            elif "gain" in kl and "dBi" in v:
                dbi = [float(x) for x in
                       re.findall(r"(?<![\d.-])(\d+(?:\.\d+)?)\s*dBi", v)]
                if dbi:
                    gains["unbanded"] = max(dbi)
            elif "beamwidth" in kl and beam is None:
                bm = re.search(r"(\d+(?:\.\d+)?)\s*°", v)
                if bm:
                    beam = float(bm.group(1))
            elif "operating frequency" in kl or kl == "frequency range":
                fr = [(float(a), float(b)) for a, b in
                      re.findall(r"(\d{3,5})\s*[-–—]\s*(\d{3,5})\s*MHz", v)]
                if fr:
                    ds_bands = [[min(a for a, _ in fr),
                                 max(b for _, b in fr)]]

    if not gains and not tx_vals:
        return None                       # no RF facts published -> skip

    # Bands: any per-band spec slug names the band (gain, TX power, MIMO).
    band_keys = set(gains)
    for k in specs:
        m = re.search(r"(?:tx-power|mimo|throughput)-(\d[\w-]*ghz|\d+-mhz)$", k)
        if m:
            band_keys.add(m.group(1))
    bands = sorted(BAND_MHZ[b] for b in band_keys if b in BAND_MHZ)
    if not bands:
        # Fall back to the operating-frequency text / datasheet table.
        of = specs.get("operating-frequency", "")
        fr = [(float(a), float(b)) for a, b in
              re.findall(r"(\d{3,5})\s*[-–]\s*(\d{3,5})\s*MHz", of)]
        if fr:
            bands = [[min(a for a, _ in fr), max(b for _, b in fr)]]
        elif ds_bands:
            bands = ds_bands
    if not bands:
        return None

    cls = default_cls
    if cls is None:                       # uisp/wireless without a sub map
        if not tx_vals:                   # gain but no radio = passive antenna
            cls = "wisp_antenna"
        elif max(gains.values(), default=0.0) >= 15:
            cls = "microwave_ptp"         # integrated dish/sector PtP
        else:
            cls = "wifi_ap"

    rf: dict = {"impedance_ohm": 50}
    if gains:
        rf["gain_dbi"] = max(gains.values())
    if tx_vals:
        rf["max_tx_power_dbm"] = max(tx_vals)
    rf["per_band"] = {b: {"gain_dbi": g} for b, g in gains.items()}

    name = p.get("title") or p.get("name") or slug
    url = f"{BASE}/{line}/{cat}/{slug}"
    rec = {
        "id": f"ubiquiti-{re.sub(r'[^a-z0-9]+', '-', slug.lower()).strip('-')}",
        "manufacturer": "Ubiquiti",
        "model": name,
        "equipment_class": cls,
        "region_of_origin": "North America",
        "environment_rating": {"ip": None, "atex": False, "temp_c": None},
        "frequency_bands_mhz": bands,
        "rf_specs": rf,
        "spatial_characteristics": (
            {"h_beamwidth_deg": beam} if beam else {}),
        "provenance": f"Ubiquiti official datasheet values via techspecs {url} "
                      "(structured specification JSON; conducted TX max, best "
                      "gain across bands).",
        "spec_confidence": "datasheet",
        "source_url": url,
    }
    ds = p.get("datasheet")
    if isinstance(ds, dict) and ds.get("url"):
        rec["datasheet_url"] = ds["url"]
    elif isinstance(ds, str) and ds:
        rec["datasheet_url"] = ds
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.4)
    args = ap.parse_args()

    bid = build_id()
    print("buildId:", bid)
    records: list[dict] = []
    for line, cat, default_cls in CATEGORIES:
        try:
            catj = json.loads(get(f"{BASE}/_next/data/{bid}/{line}/{cat}.json"))
        except Exception as exc:
            print(f"  ! category {line}/{cat}: {exc}", file=sys.stderr)
            continue
        # The vendor's own subcategory taxonomy decides the equipment class.
        sub_cls = {}
        for sub in (catj.get("pageProps") or {}).get(
                "subCategoriesWithProducts", []):
            sid = sub.get("id", "")
            if default_cls is not None:          # fixed class for the category
                c = default_cls
            elif "antenna" in sid:
                c = "wisp_antenna"
            elif any(w in sid for w in ("airfiber", "airmax", "ltu", "wave")):
                c = "microwave_ptp"
            else:
                c = None
            for pr in sub.get("products", []):
                sub_cls[pr["slug"]] = c
        slugs = sorted(sub_cls)
        if args.limit:
            slugs = slugs[: args.limit]
        print(f"{line}/{cat}: {len(slugs)} products")
        for i, slug in enumerate(slugs, 1):
            try:
                data = json.loads(
                    get(f"{BASE}/_next/data/{bid}/{line}/{cat}/{slug}.json"))
                rec = to_record(line, cat, slug, data, sub_cls.get(slug) or default_cls)
            except Exception as exc:
                print(f"  ! {slug}: {exc}", file=sys.stderr)
                rec = None
            if rec:
                records.append(rec)
            if i % 20 == 0:
                print(f"  {i}/{len(slugs)}, {len(records)} kept total")
            time.sleep(args.delay)

    uniq: dict[str, dict] = {}
    for r in records:
        uniq.setdefault(r["id"], r)
    out = {
        "_source": "Ubiquiti official techspecs (techspecs.ui.com) structured "
                   "specification JSON, fetched per product. Every RF value "
                   "is the vendor's published figure (conducted TX power, "
                   "per-band antenna gain); products without RF specs are "
                   "skipped. datasheet_url links the official PDF.",
        "devices": sorted(uniq.values(), key=lambda r: r["id"]),
    }
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {OUT.name}: {len(uniq)} devices")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
