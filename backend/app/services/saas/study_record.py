"""The study of record: what was run, on what, by which engine.

A coverage plot is evidence. It goes into a licence application, a tender
response, a safety case — documents that are read months later, by someone
who was not in the room, and sometimes disputed. For that a picture is not
enough: the reader has to be able to ask "what exactly produced this, and
does it still produce it?" and get an answer.

What was stored with each raster was its bounds, the mast position, the radius
and the headline statistics. That is enough to draw it again and nothing like
enough to defend it: the frequency, the model, the antenna, the margins, the
clutter and weather assumptions, the terrain source and the engine versions
were all gone the moment the request finished. Two studies a month apart could
differ by 20 dB and nothing on the artefact would say why.

So every study now carries:

* the **complete input set** it ran on, verbatim;
* the **provenance** — application version, propagation engine, terrain source
  and, when the exact reference engines are installed, their availability,
  because "which ITM" is a real question;
* a **digest** over both, short enough to print in a report footer and
  specific enough that two studies with the same digest ran the same way.

The record is immutable by construction: it is written once, next to the
raster, and nothing updates it. Re-running produces a *new* study with its own
id and digest, which is the honest way to show a change — not an edit to the
old one.
"""
from __future__ import annotations

import hashlib
import json

# The PRODUCT version (the installer / release line), not the API
# version in main.py: a study record answers "which build made this",
# and the answer a reader can check against a release note is this one.
APP_VERSION = "1.3.2"
RECORD_FORMAT = "antennamaster.study-record/1"


def _canonical(value: object) -> str:
    """Stable JSON for hashing: sorted keys, no incidental whitespace.

    Without this the digest would depend on dict ordering, which is an
    implementation detail — two identical studies could get different
    digests and a reader would conclude something changed when nothing did.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      default=str)


def provenance() -> dict:
    """What produced the numbers, as opposed to what was asked for."""
    from ...config import TERRARIUM_URL
    from ..rf.itm_exact import p452_available, p1812_available
    return {
        "app_version": APP_VERSION,
        "record_format": RECORD_FORMAT,
        "terrain_source": TERRARIUM_URL,
        # Which ITM/ITU engines this deployment could reach. A study run
        # without them is not wrong, but it is not the reference-grade one
        # either, and the artefact should not be silent about which it was.
        "engines": {
            "itm": "ntia_itm_1.2.2 (itmlogic)",
            "p1812": "Py1812 (ITU-R SG3 reference)" if p1812_available() else None,
            "p452": "Py452 (ITU-R SG3 reference)" if p452_available() else None,
        },
    }


def build(request: dict, stats: dict | None = None) -> dict:
    """Assemble the record for one study. Call once, at the point of run."""
    prov = provenance()
    digest = hashlib.sha256(
        (_canonical(request) + "|" + _canonical(prov)).encode()).hexdigest()
    return {
        "request": request,
        "provenance": prov,
        # 16 hex is 64 bits: short enough for a report footer, and far past
        # the point where two studies collide by accident.
        "digest": digest[:16],
        "stats": stats,
    }


def inputs_match(a: dict, b: dict) -> bool:
    """Whether two records were run on the same inputs by the same build."""
    return a.get("digest") == b.get("digest")
