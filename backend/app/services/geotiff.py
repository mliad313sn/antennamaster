"""GeoTIFF export for coverage rasters — the GIS-native format enterprise
tooling (ArcGIS, QGIS, Atoll, Pathloss import) expects.

The coverage/indoor rasters are equirectangular RGBA in EPSG:4326 (lat/lon),
so a GeoTIFF needs just three geo-tags: ModelPixelScale (degrees/pixel),
ModelTiepoint (raster origin -> the NW corner) and a minimal GeoKeyDirectory
declaring the geographic CRS.  Written with PIL alone (no GDAL/rasterio
dependency), which keeps the deployment lean.
"""
from __future__ import annotations

import io

from PIL import Image
from PIL.TiffImagePlugin import ImageFileDirectory_v2

# GeoTIFF tag numbers (OGC GeoTIFF spec).
_MODEL_PIXEL_SCALE = 33550
_MODEL_TIEPOINT = 33922
_GEO_KEY_DIRECTORY = 34735
_GEO_ASCII_PARAMS = 34737
_TIFF_DOUBLE = 12
_TIFF_SHORT = 3
_TIFF_ASCII = 2


def rgba_png_to_geotiff(png_bytes: bytes,
                        bounds: list[list[float]]) -> bytes:
    """Wrap a coverage PNG (RGBA, equirectangular) as an EPSG:4326 GeoTIFF.

    ``bounds`` is ``[[south, west], [north, east]]`` (the Leaflet overlay
    bounds the raster was rendered for).
    """
    (south, west), (north, east) = bounds
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    w, h = img.size
    dx = (east - west) / max(w, 1)
    dy = (north - south) / max(h, 1)

    ifd = ImageFileDirectory_v2()
    # Degrees per pixel in x and y (z=0). Row 0 is north, so the tiepoint
    # maps raster (0,0) to the NW corner and the scale is positive.
    ifd[_MODEL_PIXEL_SCALE] = (dx, dy, 0.0)
    ifd.tagtype[_MODEL_PIXEL_SCALE] = _TIFF_DOUBLE
    ifd[_MODEL_TIEPOINT] = (0.0, 0.0, 0.0, west, north, 0.0)
    ifd.tagtype[_MODEL_TIEPOINT] = _TIFF_DOUBLE
    # GeoKeyDirectory: version 1.1.0, 4 keys.
    #   GTModelTypeGeoKey (1024) = 2 (geographic)
    #   GTRasterTypeGeoKey (1025) = 1 (PixelIsArea)
    #   GeographicTypeGeoKey (2048) = 4326 (WGS 84)
    ifd[_GEO_KEY_DIRECTORY] = (
        1, 1, 0, 3,
        1024, 0, 1, 2,
        1025, 0, 1, 1,
        2048, 0, 1, 4326,
    )
    ifd.tagtype[_GEO_KEY_DIRECTORY] = _TIFF_SHORT
    ifd[_GEO_ASCII_PARAMS] = "WGS 84|\x00"
    ifd.tagtype[_GEO_ASCII_PARAMS] = _TIFF_ASCII

    buf = io.BytesIO()
    # Deflate keeps the transparent raster small; GIS tools read it fine.
    img.save(buf, format="TIFF", tiffinfo=ifd, compression="tiff_deflate")
    return buf.getvalue()


def world_file(bounds: list[list[float]], width: int, height: int) -> str:
    """ESRI world-file text (.wld/.pgw) for the PNG, as a fallback for tools
    that prefer a sidecar over embedded tags."""
    (south, west), (north, east) = bounds
    dx = (east - west) / max(width, 1)
    dy = (north - south) / max(height, 1)
    # A=x-scale, D=0, B=0, E=-y-scale, C=x of pixel-center (0,0), F=y of it.
    return (f"{dx:.10f}\n0.0\n0.0\n{-dy:.10f}\n"
            f"{west + dx / 2:.10f}\n{north - dy / 2:.10f}\n")
