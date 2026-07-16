#!/usr/bin/env python3
"""Install the ITU-R P.1812 digital maps for the official Py1812 engine.

The DN50/N050 refractivity maps are ITU *integral products*: they ship inside
the official Recommendation package on itu.int and may not be redistributed in
this repository. This tool downloads them from the official source (the path
the Py1812 README prescribes), extracts them into the Py1812 package, and
builds the .npz the reference code loads.

    python -m tools.fetch_itu_maps
"""
from __future__ import annotations

import io
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ITU_ZIP = ("https://www.itu.int/dms_pubrec/itu-r/rec/p/"
           "R-REC-P.1812-8-202509-I!!ZIP-E.zip")


def main() -> int:
    try:
        import Py1812  # noqa: F401
    except FileNotFoundError:
        # Package present but maps missing — that is exactly what we fix.
        pass
    except ImportError:
        print("Py1812 is not installed: pip install git+https://github.com/eeveetza/Py1812")
        return 1

    import importlib.util
    spec = importlib.util.find_spec("Py1812")
    pkg_dir = Path(spec.origin).parent
    maps_dir = pkg_dir / "maps"
    maps_dir.mkdir(exist_ok=True)

    if (pkg_dir / "P1812.npz").exists():
        print(f"maps already installed: {pkg_dir / 'P1812.npz'}")
        _setup_p452(maps_dir)
        return 0

    print(f"downloading ITU digital maps from {ITU_ZIP} …")
    with urllib.request.urlopen(ITU_ZIP, timeout=180) as r:
        data = r.read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(maps_dir)
    print(f"extracted {len(list(maps_dir.iterdir()))} files → {maps_dir}")

    subprocess.run([sys.executable, "initiate_digital_maps.py"],
                   cwd=pkg_dir, check=True)
    print(f"built {pkg_dir / 'P1812.npz'} — P.1812 reference engine ready")
    _setup_p452(maps_dir)
    return 0


def _setup_p452(p1812_maps: Path) -> None:
    """P.452-18 uses the same DN50/N050 integral maps; if the official Py452
    package is installed, build its .npz from the files just downloaded."""
    import importlib.util
    spec = importlib.util.find_spec("Py452")
    if spec is None:
        print("Py452 not installed (optional): "
              "pip install git+https://github.com/eeveetza/Py452")
        return
    pkg_dir = Path(spec.origin).parent
    if (pkg_dir / "P452.npz").exists():
        print(f"P.452 maps already installed: {pkg_dir / 'P452.npz'}")
        return
    maps_dir = pkg_dir / "maps"
    maps_dir.mkdir(exist_ok=True)
    import shutil
    for name in ("DN50.TXT", "N050.TXT"):
        src = p1812_maps / name
        if not src.exists():
            print(f"! {name} not found in {p1812_maps}; skipping P.452 setup")
            return
        shutil.copy(src, maps_dir / name)
    subprocess.run([sys.executable, "initiate_digital_maps.py"],
                   cwd=pkg_dir, check=True)
    print(f"built {pkg_dir / 'P452.npz'} — P.452-18 reference engine ready")


if __name__ == "__main__":
    raise SystemExit(main())
