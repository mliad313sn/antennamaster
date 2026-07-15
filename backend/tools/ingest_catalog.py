#!/usr/bin/env python3
"""Regenerate the hardware catalog from the curated source records.

    python -m tools.ingest_catalog            # regenerate app/data/hardware_catalog.json
    python -m tools.ingest_catalog --dry-run  # print stats only

Runs the async ingestion pipeline (normalize → deduplicate) over every JSON in
``app/data/catalog_sources/`` and merges the result with the legacy generic
profiles already in the catalog. Idempotent: re-running reproduces the same
file. New source records are added by dropping a JSON into ``catalog_sources``
(or, at a customer site, into ``AM_DATA_DIR`` — see hardware.py).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Allow running as a script from the backend directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.rf.catalog_ingest import deduplicate, ingest_sources  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "app" / "data" / "hardware_catalog.json"
SOURCES = ROOT / "app" / "data" / "catalog_sources"


async def build() -> dict:
    source_files = sorted(str(p) for p in SOURCES.glob("*.json"))
    result = await ingest_sources(source_files)

    # Preserve the legacy generic profiles (those without the rich schema).
    legacy = []
    if CATALOG.exists():
        cur = json.loads(CATALOG.read_text())
        for e in cur.get("equipment", []):
            if "equipment_class" not in e:
                legacy.append(e)

    combined = legacy + result["equipment"]
    # Final cross-dedup (legacy entries lack a fingerprint, so never falsely merge).
    combined, _ = deduplicate(combined)
    combined.sort(key=lambda e: (e.get("category", ""), e.get("model", "")))

    by_region: dict[str, int] = {}
    by_class: dict[str, int] = {}
    by_conf: dict[str, int] = {}
    for e in combined:
        by_region[e.get("region_of_origin", "Unknown")] = by_region.get(e.get("region_of_origin", "Unknown"), 0) + 1
        by_class[e.get("equipment_class", "legacy_generic")] = by_class.get(e.get("equipment_class", "legacy_generic"), 0) + 1
        by_conf[e.get("spec_confidence", "legacy")] = by_conf.get(e.get("spec_confidence", "legacy"), 0) + 1

    return {
        "_meta": {
            "description": (
                "AntennaMaster hardware catalog. Entries with 'equipment_class' "
                "come from curated source records (app/data/catalog_sources/) "
                "carrying per-record 'provenance' and 'spec_confidence' "
                "(datasheet | published_typical | class_reference). Values marked "
                "class_reference are engineering-standard planning figures for the "
                "family, NOT vendor datasheet guarantees — confirm the exact SKU "
                "before design. Extend by dropping a JSON into catalog_sources or "
                "AM_DATA_DIR and re-running tools/ingest_catalog.py."
            ),
            "version": 2,
            "counts": {
                "total": len(combined),
                "legacy_generic": len(legacy),
                "ingested": len(result["equipment"]),
                "merged_rebrands": result["stats"]["merged_rebrands"],
                "by_equipment_class": dict(sorted(by_class.items())),
                "by_region": dict(sorted(by_region.items())),
                "by_confidence": dict(sorted(by_conf.items())),
            },
        },
        "equipment": combined,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    catalog = asyncio.run(build())
    print(json.dumps(catalog["_meta"]["counts"], indent=2))
    if args.dry_run:
        return
    CATALOG.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
    print(f"\nwrote {CATALOG}")


if __name__ == "__main__":
    main()
