"""The equipment catalog must not fabricate the specs a study depends on.

Two failures, in opposite directions, both labelled spec_confidence
"datasheet":

  * every entry without a stated beamwidth defaulted to 360 deg, so a 27 dBi
    point-to-point dish was served as an omni. The UI reads 360 as "not
    directional", so selecting one painted a full-circle donut at dish gain -
    a map claiming a whole township off one CPE.
  * entries without a stated sensitivity silently inherited the class default
    (-70 dBm for the LTU family, whose real sensitivity is near -96).
"""
import math

import pytest

from app.services.rf.catalog_ingest import beamwidth_for, confidence_for
from app.services.rf.hardware import list_equipment

CATALOG = list_equipment()


def test_catalog_is_not_empty():
    assert len(CATALOG) > 50


def test_no_high_gain_entry_claims_to_be_omnidirectional():
    """An omni cannot focus 15+ dBi; serving one as 360 deg is a fiction that
    over-states coverage by orders of magnitude."""
    offenders = [e["id"] for e in CATALOG
                 if e["antenna_gain_dbi"] > 15.0 and e["beamwidth_deg"] >= 360.0]
    assert offenders == [], offenders


def test_every_entry_declares_where_its_beamwidth_came_from():
    for e in CATALOG:
        assert e["beamwidth_source"] in {
            "datasheet", "inferred_from_gain", "assumed_omni"}, e["id"]
        if e["beamwidth_source"] == "assumed_omni":
            assert e["antenna_gain_dbi"] <= 15.0, e["id"]


def test_invented_specs_are_never_labelled_datasheet():
    """The confidence label is what a planner trusts when they cannot check.

    "Invented" means a number this catalog produced: a beamwidth derived from
    gain, or a sensitivity inherited from the class default. An omni assumed
    for a low-gain device is the physically-sound default for that class, not
    an invention, so it does not disqualify the label.
    """
    for e in CATALOG:
        if e.get("spec_confidence") == "datasheet":
            assert e["beamwidth_source"] != "inferred_from_gain", e["id"]
            assert e["sensitivity_source"] == "datasheet", e["id"]


def test_derived_beamwidth_matches_the_aperture_relation():
    """theta = sqrt(29000 / 10^(G/10)) - the standard gain/beamwidth identity.
    Spot-checked against real datasheets: a 27 dBi MikroTik LHG XL is ~7 deg."""
    bw, source = beamwidth_for({}, 27.0)
    assert source == "inferred_from_gain"
    assert bw == pytest.approx(math.sqrt(29000.0 / 10 ** 2.7), abs=0.1)
    assert 6.0 < bw < 9.0

    # A stated beamwidth always wins over the derivation.
    assert beamwidth_for({"h_beamwidth_deg": 30.0}, 27.0) == (30.0, "datasheet")
    # Low gain stays omni - we do not invent directionality either.
    assert beamwidth_for({}, 8.0) == (360.0, "assumed_omni")


def test_confidence_downgrades_on_any_fallback():
    assert confidence_for("datasheet", True, "datasheet") == "datasheet"
    assert confidence_for("datasheet", False, "datasheet") == "inferred"
    assert confidence_for("datasheet", True, "inferred_from_gain") == "inferred"
    # A record that never claimed datasheet is left as it is.
    assert confidence_for("class_reference", False, "assumed_omni") == "class_reference"


def test_a_directional_entry_reaches_the_selector_as_a_sector():
    """The UI turns on sector mode when beamwidth < 360; this is the contract
    that makes a dish paint a beam instead of a disc."""
    ltu = next(e for e in CATALOG if e["id"] == "ubiquiti-ltu-lr")
    assert ltu["beamwidth_deg"] < 360.0
    assert ltu["antenna_gain_dbi"] > 20.0
