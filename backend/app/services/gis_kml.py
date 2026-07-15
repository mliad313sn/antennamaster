"""KML/KMZ generation for GIS interoperability (Google Earth, QGIS, ArcGIS).

Exports a point-to-point study as standard KML: TX and RX placemarks plus the
line-of-sight path and the terrain profile beneath it, so an engineer can drop
the link straight into Google Earth for review or a client deliverable.
Hand-built KML (no external dependency) — the same approach used for the
coverage KMZ GroundOverlay.
"""
from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape


def _coord(lon: float, lat: float, alt: float) -> str:
    return f"{lon:.7f},{lat:.7f},{alt:.1f}"


def los_kml(*, tx_lat: float, tx_lon: float, rx_lat: float, rx_lon: float,
            tx_ground_m: float, rx_ground_m: float,
            tx_height_m: float, rx_height_m: float,
            terrain: list[tuple[float, float, float]] | None = None,
            los_clear: bool | None = None,
            title: str = "AntennaMaster link") -> str:
    """KML document for a TX→RX link.

    ``terrain`` is an optional list of (lon, lat, ground_elev_m) samples along
    the path, drawn clamped to the ground so the terrain crossing is visible.
    ``los_clear`` colours the LOS line green (clear) or red (obstructed).
    """
    tx_alt = tx_ground_m + tx_height_m
    rx_alt = rx_ground_m + rx_height_m
    los_colour = "ff00ff00" if los_clear else "ff0000ff"  # KML aabbggrr
    if los_clear is None:
        los_colour = "ffff8800"

    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        '<Document>',
        f'<name>{escape(title)}</name>',
        # Styles.
        '<Style id="tx"><IconStyle><color>ff2a78d6</color>'
        '<scale>1.2</scale></IconStyle></Style>',
        '<Style id="rx"><IconStyle><color>ff00a86b</color>'
        '<scale>1.2</scale></IconStyle></Style>',
        f'<Style id="los"><LineStyle><color>{los_colour}</color>'
        '<width>2.5</width></LineStyle></Style>',
        '<Style id="terrain"><LineStyle><color>b0787878</color>'
        '<width>1.5</width></LineStyle></Style>',
        # TX / RX placemarks (absolute altitude = ground + antenna height).
        '<Placemark><name>TX</name><styleUrl>#tx</styleUrl>'
        '<Point><altitudeMode>absolute</altitudeMode>'
        f'<coordinates>{_coord(tx_lon, tx_lat, tx_alt)}</coordinates></Point></Placemark>',
        '<Placemark><name>RX</name><styleUrl>#rx</styleUrl>'
        '<Point><altitudeMode>absolute</altitudeMode>'
        f'<coordinates>{_coord(rx_lon, rx_lat, rx_alt)}</coordinates></Point></Placemark>',
        # Line of sight (antenna to antenna).
        '<Placemark><name>Line of sight</name><styleUrl>#los</styleUrl>'
        '<LineString><extrude>0</extrude><altitudeMode>absolute</altitudeMode>'
        f'<coordinates>{_coord(tx_lon, tx_lat, tx_alt)} '
        f'{_coord(rx_lon, rx_lat, rx_alt)}</coordinates></LineString></Placemark>',
    ]
    if terrain:
        pts = " ".join(_coord(lon, lat, elev) for lon, lat, elev in terrain)
        parts.append(
            '<Placemark><name>Terrain profile</name><styleUrl>#terrain</styleUrl>'
            '<LineString><altitudeMode>absolute</altitudeMode>'
            f'<coordinates>{pts}</coordinates></LineString></Placemark>')
    parts += ['</Document>', '</kml>']
    return "\n".join(parts)


def kmz_wrap(kml: str, inner_name: str = "doc.kml") -> bytes:
    """Zip a KML string into a KMZ archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(inner_name, kml)
    return buf.getvalue()
