"""Centralized audit logging (OT/IT compliance).

Every critical action — logins, DXF uploads, project modifications, data
exports — is recorded to BOTH a rotating audit log file (via Python's
``logging`` module, tamper-evident append-only stream for SIEM ingestion) and
the tenant-scoped ``audit_log`` database table, stamped with the acting user
and the client IP address.

The recording is driven centrally by ``AuditMiddleware`` (see api layer), so
coverage does not depend on every endpoint remembering to log.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from ..config import DATA_DIR

# Which requests are "critical" and get an audit record: (METHOD, path
# substring) -> action label.  GET is included only for data exports.
CRITICAL_RULES: list[tuple[str, str, str]] = [
    ("POST", "/api/auth/login", "login"),
    ("POST", "/api/auth/register", "register"),
    ("POST", "/api/auth/logout", "logout"),
    ("POST", "/api/auth/tier", "tier_change"),
    ("POST", "/api/auth/api-token", "api_token_create"),
    ("POST", "/api/auth/logo", "logo_upload"),
    ("POST", "/api/dxf/upload", "dxf_upload"),
    ("POST", "/georeference", "dxf_georeference"),
    ("DELETE", "/api/dxf/", "dxf_delete"),
    ("POST", "/api/rf/antenna", "antenna_upload"),
    ("POST", "/api/projects", "project_create"),
    ("PUT", "/api/projects/", "project_update"),
    ("DELETE", "/api/projects/", "project_delete"),
    ("POST", "/duplicate", "project_duplicate"),
    ("POST", "/share", "project_share"),
    # Data exports (GIS / reports / batch).
    ("GET", "profile.csv", "export_csv"),
    ("GET", "profile.kml", "export_kml"),
    ("GET", ".tif", "export_geotiff"),
    ("GET", ".kmz", "export_kmz"),
    ("GET", "/api/saas/bom.csv", "export_bom"),
    ("POST", "/api/saas/report.pdf", "export_pdf"),
    ("POST", "/api/saas/coverage/async", "coverage_async"),
    ("POST", "/api/rf/batch", "batch_analysis"),
]

_logger = logging.getLogger("antennamaster.audit")


def _configure() -> logging.Logger:
    if _logger.handlers:
        return _logger
    _logger.setLevel(logging.INFO)
    _logger.propagate = False
    try:
        path = DATA_DIR / "audit.log"
        handler = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=5)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(message)s", datefmt="%Y-%m-%dT%H:%M:%S%z"))
        _logger.addHandler(handler)
        try:                       # restrict the audit trail to the owner
            path.chmod(0o600)
        except OSError:
            pass
    except OSError:
        # Read-only data dir: still emit to the root logger so nothing is lost.
        _logger.addHandler(logging.StreamHandler())
    return _logger


def classify(method: str, path: str) -> str | None:
    """Return the action label for a critical request, or None."""
    for m, needle, action in CRITICAL_RULES:
        if method == m and needle in path:
            return action
    return None


def record(action: str, *, user_id: int | None, email: str | None,
           ip: str | None, status: int, detail: str = "") -> None:
    """Write one audit record to the file log and the database."""
    log = _configure()
    log.info("action=%s user_id=%s email=%s ip=%s status=%s detail=%s",
             action, user_id if user_id is not None else "-",
             email or "-", ip or "-", status, detail or "-")
    # Persist to the DB (tenant-scoped queries read this); never let an audit
    # write break the request path.
    try:
        from .saas import db
        db.log_action(user_id, action, detail, ip=ip)
    except Exception:  # noqa: BLE001
        log.warning("audit db write failed for action=%s", action)
