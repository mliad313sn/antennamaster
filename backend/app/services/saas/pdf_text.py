"""Escaping for text that reaches a ReportLab ``Paragraph``.

A Paragraph is not a plain string sink: it parses a small HTML dialect, so
every user-supplied value interpolated into one — a site name, an operator,
free-text notes, the organisation on a report header, a project title — is
markup. Two consequences, both visible on documents that get signed and
filed:

* **Text disappears.** A perfectly ordinary mast name like
  ``Mast A & B <north>`` renders as ``Mast A & B``: the parser swallows
  ``<north>`` as an unknown tag. A compliance dossier that names the wrong
  structure is worse than one that fails to generate.
* **The document can be forged.** ``<font color="white">`` hides text,
  ``<b>``/``<br/>`` restructure it, and ``<img src="...">`` pulls a local
  file into the page. On an EMF assessment whose whole purpose is to state a
  compliance distance to a regulator, letting the *input* control the
  rendering is a integrity problem, not a cosmetic one.

Escaping the three characters that open the dialect is the whole fix — and it
must be applied at every interpolation site, which is why this is one shared
function rather than a habit.
"""
from __future__ import annotations


def esc(value: object) -> str:
    """Render ``value`` as literal text inside a ReportLab Paragraph."""
    return (str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))
