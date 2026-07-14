"""Wall/obstacle material attenuation library for indoor & underground studies.

Per-crossing losses in dB, tabulated at three anchor frequencies (900 MHz,
2.4 GHz, 5.8 GHz — values consolidated from ITU-R P.2040 measurements and
the COST-231 multi-wall literature) and log-frequency interpolated in
between (clamped at the ends).  These feed the COST-231 multi-wall engine
in ``engine.py``.
"""
from __future__ import annotations

import numpy as np

# key -> (label, loss@900MHz, loss@2400MHz, loss@5800MHz) in dB per crossing
MATERIALS: dict[str, dict] = {
    "drywall":        {"label": "Drywall / plasterboard",       "loss": (2.0, 3.0, 4.0)},
    "wood":           {"label": "Wood / door",                  "loss": (3.0, 4.0, 6.0)},
    "glass":          {"label": "Glass (plain)",                "loss": (1.5, 2.0, 3.0)},
    "glass_coated":   {"label": "Glass (low-E coated)",         "loss": (10.0, 12.0, 15.0)},
    "brick":          {"label": "Brick wall",                   "loss": (6.0, 8.0, 12.0)},
    "concrete":       {"label": "Concrete 20 cm",               "loss": (10.0, 13.0, 20.0)},
    "concrete_thick": {"label": "Reinforced concrete 30 cm+",   "loss": (18.0, 23.0, 32.0)},
    "metal":          {"label": "Metal / shielding",            "loss": (26.0, 30.0, 35.0)},
    "rock":           {"label": "Rock pillar (mine)",           "loss": (25.0, 35.0, 45.0)},
    "soil":           {"label": "Earth / backfill",             "loss": (30.0, 45.0, 60.0)},
    "elevator":       {"label": "Elevator / machinery",         "loss": (20.0, 25.0, 30.0)},
    "none":           {"label": "Ignore (decorative layer)",    "loss": (0.0, 0.0, 0.0)},
}

_ANCHORS_MHZ = np.array([900.0, 2400.0, 5800.0])


def material_loss_db(material: str, freq_mhz: float) -> float:
    """Per-crossing loss of a material at ``freq_mhz`` (log-f interpolated)."""
    if material not in MATERIALS:
        raise ValueError(f"Unknown material: {material!r}")
    losses = np.asarray(MATERIALS[material]["loss"], dtype=np.float64)
    f = float(np.clip(freq_mhz, _ANCHORS_MHZ[0], _ANCHORS_MHZ[-1]))
    return float(np.interp(np.log10(f), np.log10(_ANCHORS_MHZ), losses))


def list_materials() -> list[dict]:
    return [{"key": k, "label": v["label"],
             "loss_900": v["loss"][0], "loss_2400": v["loss"][1],
             "loss_5800": v["loss"][2]}
            for k, v in MATERIALS.items()]


def guess_material(layer_name: str) -> str:
    """Heuristic default material from a DXF layer name."""
    n = layer_name.lower()
    for pattern, mat in (
        ("concrete", "concrete"), ("beton", "concrete"), ("rc", "concrete_thick"),
        ("brick", "brick"), ("masonry", "brick"), ("mur", "brick"),
        ("glass", "glass"), ("window", "glass"), ("fenetre", "glass"),
        ("metal", "metal"), ("steel", "metal"), ("shaft", "metal"),
        ("elev", "elevator"), ("lift", "elevator"),
        ("rock", "rock"), ("pillar", "rock"), ("mine", "rock"),
        ("door", "wood"), ("porte", "wood"), ("wood", "wood"),
        ("partition", "drywall"), ("gips", "drywall"), ("dry", "drywall"),
        ("wall", "brick"),
    ):
        if pattern in n:
            return mat
    return "drywall"
