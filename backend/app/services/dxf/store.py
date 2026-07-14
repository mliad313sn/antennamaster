"""In-process registry of uploaded DXF documents and their derived state.

Each upload gets a UUID.  The raw file is persisted under DXF_STORE_DIR so
a restarted server can lazily re-open it; parsed documents, terrain grids
and georeferencing transforms are kept in memory per process.
"""
from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ezdxf.document import Drawing

from .georef import BaseGeoref, build_georef
from .gridder import DxfTerrainGrid, build_grid
from .parser import extract_points, load_dxf
from ...config import DXF_STORE_DIR


@dataclass
class DxfSession:
    dxf_id: str
    filename: str
    path: Path
    doc: Drawing | None = None
    layers: list[dict] = field(default_factory=list)
    selected_layers: list[str] | None = None
    georef: BaseGeoref | None = None
    grid: DxfTerrainGrid | None = None
    georef_params: dict | None = None      # raw request params, persisted
    validation: dict | None = None
    overlay_png: bytes | None = None
    overlay_bounds: list[list[float]] | None = None
    footprint: list[list[float]] | None = None

    def document(self) -> Drawing:
        if self.doc is None:
            self.doc = load_dxf(str(self.path))
        return self.doc

    # ---------------------------------------------------------- persistence
    # The derived grid/georef must survive process restarts and be
    # reconstructible by ANY uvicorn worker, not just the one that ran the
    # georeferencing.  We persist the *inputs* (georef params + layer
    # selection) as a JSON sidecar and rebuild deterministically on demand -
    # cheaper and more robust than pickling numpy grids.
    def _state_path(self) -> Path:
        return self.path.with_suffix(".state.json")

    def persist_state(self) -> None:
        self._state_path().write_text(json.dumps({
            "filename": self.filename,
            "selected_layers": self.selected_layers,
            "georef_params": self.georef_params,
            "validation": self.validation,
            "footprint": self.footprint,
            "overlay_bounds": self.overlay_bounds,
        }))

    def ensure_ready(self) -> bool:
        """True when grid+georef are available, rebuilding from the persisted
        sidecar if this process has never seen the georeferencing."""
        if self.grid is not None and self.georef is not None:
            return True
        if self.georef_params is None and self._state_path().exists():
            data = json.loads(self._state_path().read_text())
            self.filename = data.get("filename", self.filename)
            self.selected_layers = data.get("selected_layers")
            self.georef_params = data.get("georef_params")
            self.validation = data.get("validation")
            self.footprint = data.get("footprint")
            self.overlay_bounds = data.get("overlay_bounds")
        if self.georef_params is None:
            return False
        georef = build_georef(self.georef_params)
        points = extract_points(self.document(), self.selected_layers)
        self.grid = build_grid(points, z_scale=georef.z_scale)
        self.georef = georef
        return True


class DxfStore:
    def __init__(self, base_dir: Path = DXF_STORE_DIR):
        self.base_dir = Path(base_dir)
        self._sessions: dict[str, DxfSession] = {}
        self._lock = threading.Lock()

    def create(self, filename: str, content: bytes) -> DxfSession:
        dxf_id = uuid.uuid4().hex[:12]
        path = self.base_dir / f"{dxf_id}.dxf"
        path.write_bytes(content)
        session = DxfSession(dxf_id=dxf_id, filename=filename, path=path)
        with self._lock:
            self._sessions[dxf_id] = session
        return session

    def get(self, dxf_id: str) -> DxfSession | None:
        with self._lock:
            session = self._sessions.get(dxf_id)
        if session is None:
            # Lazy rehydration after a server restart: the raw file survives.
            path = self.base_dir / f"{dxf_id}.dxf"
            if path.exists():
                session = DxfSession(dxf_id=dxf_id, filename=path.name, path=path)
                with self._lock:
                    self._sessions[dxf_id] = session
        return session

    def delete(self, dxf_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(dxf_id, None)
        path = self.base_dir / f"{dxf_id}.dxf"
        if path.exists():
            path.unlink()
        return session is not None or path.exists() is False


_store = DxfStore()


def get_dxf_store() -> DxfStore:
    return _store
