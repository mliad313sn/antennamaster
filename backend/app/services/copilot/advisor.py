"""Engine-driven design advisor -- the reasoning layer of the copilot.

The tool answers "what is the coverage of *this*"; the advisor answers "what
should I DO about it".  It turns a study's numbers into ranked, *actionable*
findings -- each with the cause, the physics reason and a quantified fix
(raise the mast to X m, add Y dBi of gain, drop to a lower band, add a
repeater).  It is fully deterministic and runs air-gapped: no API key, no
network -- so a mine electrician gets the same defensible advice as an RF
engineer.  An optional Claude-backed narrator (``narrate_llm``) can rephrase
the findings in prose when an API key is configured, but never gates the
advice.
"""
from __future__ import annotations

import numpy as np

# Design target: a healthy link carries this much fade margin over sensitivity.
HEALTHY_MARGIN_DB = 10.0


def _finding(severity: str, issue: str, why: str, action: str) -> dict:
    return {"severity": severity, "issue": issue, "why": why, "action": action}


def advise_link(analysis: dict, heights: dict | None = None) -> list[dict]:
    """Rank findings for a point-to-point link study.

    ``analysis`` carries margin_db, los_clear, fresnel_clearance_ratio,
    diffraction_loss_db, distance_m and freq_mhz (the /profile study output).
    ``heights`` is the optional /optimize-heights result, used to quote the
    exact mast height that fixes an obstruction.
    """
    out: list[dict] = []
    margin = float(analysis.get("margin_db", 0.0))
    los = bool(analysis.get("los_clear", True))
    fres = float(analysis.get("fresnel_clearance_ratio", 1.0))
    diff = float(analysis.get("diffraction_loss_db", 0.0))
    dist_km = float(analysis.get("distance_m", 0.0)) / 1000.0
    freq = float(analysis.get("freq_mhz", 0.0))

    # --- obstruction / clearance -----------------------------------------
    if not los or fres < 0.6:
        fix = "raise an antenna or relocate the mast to clear the terrain"
        if heights:
            f1 = (heights.get("criteria", {}).get("f1_60", {})
                  or {}).get("min_tx_height_m")
            if f1:
                fix = f"raise the TX mast to ~{f1:g} m for 60% Fresnel clearance"
            elif (heights.get("criteria", {}).get("los", {})
                  or {}).get("min_tx_height_m") is None:
                fix = ("no achievable mast height clears the path - insert a "
                       "repeater/relay near the blocking ridge, or reroute")
        out.append(_finding(
            "critical" if not los else "warning",
            "Path is obstructed" if not los else "Insufficient Fresnel clearance",
            f"line-of-sight is {'blocked' if not los else 'grazing'} "
            f"(clearance ratio {fres:.2f}; a link needs >=0.6 of the first "
            "Fresnel radius), so diffraction dominates the loss",
            fix))

    if diff > 15.0:
        out.append(_finding(
            "warning", "High diffraction loss",
            f"{diff:.0f} dB is lost bending over terrain edges; diffraction "
            "loss falls fast with extra clearance",
            "gain clearance (height/relocation) or accept the loss in the budget"))

    # --- budget ----------------------------------------------------------
    if margin < 0.0:
        deficit = -margin
        freq_factor = 10.0 ** (deficit / 20.0)
        target_mhz = freq / freq_factor if freq else 0.0
        out.append(_finding(
            "critical", "Link does not close",
            f"received power is {deficit:.1f} dB below sensitivity",
            f"close {deficit:.1f} dB by any of: +{deficit:.0f} dBi antenna "
            f"gain, +{deficit:.0f} dB TX power (regulations permitting), "
            + (f"a lower band (~{target_mhz:.0f} MHz has {deficit:.0f} dB "
               "less free-space loss), " if target_mhz else "")
            + "or a repeater that halves the hop"))
    elif margin < HEALTHY_MARGIN_DB:
        out.append(_finding(
            "warning", "Thin fade margin",
            f"only {margin:.1f} dB over sensitivity; rain, foliage and "
            "multipath fading can exceed this",
            f"add ~{HEALTHY_MARGIN_DB - margin:.0f} dB (gain/height) for a "
            "weather-robust link"))

    if freq >= 10_000.0 and dist_km > 10.0:
        out.append(_finding(
            "warning", "High band over a long hop",
            f"{freq / 1000:.0f} GHz over {dist_km:.0f} km is rain-fade and "
            "gaseous-absorption sensitive",
            "verify rain-region availability, or use a lower band for the span"))

    if not out:
        out.append(_finding(
            "good", "Healthy link",
            f"{margin:.1f} dB margin with a clear path", "no action required"))
    order = {"critical": 0, "warning": 1, "good": 2}
    out.sort(key=lambda f: order.get(f["severity"], 3))
    return out


def advise_coverage(stats: dict, tech: dict | None = None,
                    sinr: dict | None = None) -> list[dict]:
    """Rank findings for an area coverage / multi-site study."""
    out: list[dict] = []
    served = float(stats.get("served_area_fraction", 0.0))
    freq = float((tech or {}).get("freq_mhz", 0.0))

    if served < 0.75:
        out.append(_finding(
            "critical", "Large coverage holes",
            f"only {served * 100:.0f}% of the area is served",
            "raise the mast (see height optimizer), add a site (site-search "
            "finds the best position), or add a lower coverage band"))
    elif served < 0.9:
        out.append(_finding(
            "warning", "Partial coverage",
            f"{served * 100:.0f}% served - fringe and shadowed pockets remain",
            "a sector antenna aimed at the demand, more downtilt tuning, or a "
            "small fill-in site closes most residual holes"))

    if sinr:
        mean_sinr = float(sinr.get("mean_sinr_db", 99.0))
        if mean_sinr < 6.0:
            out.append(_finding(
                "warning", "Interference-limited",
                f"mean SINR {mean_sinr:.1f} dB - co-channel sites overlap",
                "increase frequency reuse distance, add downtilt, or assign "
                "non-overlapping channels between the worst-offending sites"))

    if freq and freq >= 3000.0 and served < 0.9:
        out.append(_finding(
            "warning", "High band coverage layer",
            f"{freq / 1000:.1f} GHz penetrates and diffracts poorly for area "
            "coverage",
            "add a sub-GHz coverage layer under the capacity band"))

    if not out:
        out.append(_finding(
            "good", "Solid coverage",
            f"{served * 100:.0f}% of the area served", "no action required"))
    order = {"critical": 0, "warning": 1, "good": 2}
    out.sort(key=lambda f: order.get(f["severity"], 3))
    return out


def narrate(findings: list[dict], subject: str = "study") -> str:
    """Plain-language summary of the findings (deterministic, offline)."""
    crit = [f for f in findings if f["severity"] == "critical"]
    warn = [f for f in findings if f["severity"] == "warning"]
    if not crit and not warn:
        return f"This {subject} looks healthy: {findings[0]['why']}."
    parts = [f"This {subject} has "
             + (f"{len(crit)} blocking issue(s)" if crit else "")
             + (" and " if crit and warn else "")
             + (f"{len(warn)} thing(s) to improve" if warn else "") + "."]
    for f in crit + warn:
        parts.append(f"- {f['issue']}: {f['action']}.")
    return " ".join(parts[:1]) + "\n" + "\n".join(parts[1:])


def narrate_llm(findings: list[dict], subject: str, context: str = "") -> str:
    """Optional Claude-backed narration; falls back to ``narrate`` when no API
    key is configured or the call fails (keeps the copilot air-gapped-safe)."""
    import os
    key = os.environ.get("AM_ANTHROPIC_API_KEY") or os.environ.get(
        "ANTHROPIC_API_KEY")
    if not key:
        return narrate(findings, subject)
    try:  # best-effort; never let the network break the advice
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model=os.environ.get("AM_COPILOT_MODEL", "claude-sonnet-5"),
            max_tokens=400,
            messages=[{"role": "user", "content":
                       f"You are an RF design assistant. In 3-4 sentences, "
                       f"explain this {subject} to a non-specialist and give "
                       f"the top fix. Context: {context}. Findings: {findings}"}])
        return "".join(b.text for b in msg.content if hasattr(b, "text"))
    except Exception:
        return narrate(findings, subject)
