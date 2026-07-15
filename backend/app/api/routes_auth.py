"""Authentication, accounts, tiers, audit and white-label branding."""
from __future__ import annotations

import os
import threading
import time

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel, EmailStr, Field

from ..config import DATA_DIR
from ..services.saas import db
from ..services.saas.tiers import TIER_INFO, require_feature, saas_mode

router = APIRouter(prefix="/api/auth", tags=["saas"])

LOGO_DIR = DATA_DIR / "logos"
LOGO_DIR.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------- login brute-force guard
# Simple in-process lockout: N failures per account within the window locks
# further attempts out until the window expires. Per-worker state is enough
# to break online brute force given the PBKDF2 cost per attempt.
_FAILS: dict[str, list[float]] = {}
_FAILS_LOCK = threading.Lock()
_LOCKOUT_N = 8
_LOCKOUT_WINDOW_S = 900.0


def _login_locked(email: str) -> bool:
    now = time.time()
    with _FAILS_LOCK:
        attempts = [t for t in _FAILS.get(email, []) if now - t < _LOCKOUT_WINDOW_S]
        _FAILS[email] = attempts
        return len(attempts) >= _LOCKOUT_N


def _login_failed(email: str) -> None:
    with _FAILS_LOCK:
        _FAILS.setdefault(email, []).append(time.time())
        if len(_FAILS) > 10_000:            # bound the tracking dict itself
            _FAILS.pop(next(iter(_FAILS)))


# ------------------------------------------------------------ dependencies
def current_user(authorization: str | None = Header(None)) -> dict | None:
    """Optional bearer auth: returns the user dict or None (anonymous)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return db.user_for_token(authorization.split(" ", 1)[1].strip())


def required_user(user: dict | None = Depends(current_user)) -> dict:
    if user is None:
        raise HTTPException(401, "Authentication required")
    return user


def _public(user: dict) -> dict:
    return {k: user[k] for k in ("id", "email", "name", "role", "tier",
                                 "org_name") if k in user} | {
        "has_logo": bool(user.get("logo_path"))}


# ---------------------------------------------------------------- schemas
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str = ""
    role: str = Field("field", pattern="^(manager|field|presales)$")
    org_name: str = ""


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TierIn(BaseModel):
    tier: str = Field(pattern="^(basic|pro|enterprise)$")


# --------------------------------------------------------------- endpoints
@router.post("/register")
def register(request: Request, body: RegisterIn) -> dict:
    if db.get_user_by_email(body.email):
        raise HTTPException(409, "An account with this email already exists")
    user = db.create_user(body.email, body.password, name=body.name,
                          role=body.role, org_name=body.org_name)
    token = db.issue_token(user["id"])
    # The audit middleware records this with the client IP; the request has no
    # token yet, so stamp the identity it should attribute the action to.
    request.state.audit_user_id = user["id"]
    request.state.audit_email = user["email"]
    request.state.audit_detail = f"role={body.role}"
    return {"token": token, "user": _public(user)}


@router.post("/login")
def login(request: Request, body: LoginIn) -> dict:
    email = body.email.lower()
    if _login_locked(email):
        raise HTTPException(429, "Too many failed attempts - try again later")
    user = db.get_user_by_email(email)
    if user is None or not db.verify_password(body.password, user["password_hash"]):
        _login_failed(email)
        raise HTTPException(401, "Invalid email or password")
    token = db.issue_token(user["id"])
    request.state.audit_user_id = user["id"]
    request.state.audit_email = user["email"]
    return {"token": token, "user": _public(user)}


@router.post("/logout")
def logout(authorization: str | None = Header(None)) -> dict:
    """Revoke the presented session token."""
    if authorization and authorization.lower().startswith("bearer "):
        db.revoke_token(authorization.split(" ", 1)[1].strip())
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(required_user)) -> dict:
    return {"user": _public(user)}


@router.get("/tiers")
def tiers() -> dict:
    """Public plan matrix for the pricing/upgrade UI."""
    return {"tiers": TIER_INFO}


@router.post("/tier")
def set_tier(body: TierIn, user: dict = Depends(required_user),
             x_billing_secret: str | None = Header(None)) -> dict:
    """Plan change. In open (self-hosted) mode this is self-serve for
    evaluation. In SaaS mode (AM_SAAS_MODE=1) it simulates the billing
    provider's webhook and REQUIRES the AM_BILLING_SECRET header - users
    must not be able to grant themselves Enterprise for free."""
    if saas_mode():
        secret = os.environ.get("AM_BILLING_SECRET", "")
        if not secret or x_billing_secret != secret:
            raise HTTPException(
                403, "Plan changes in SaaS mode are made by the billing "
                     "provider, not the client.")
    db.update_user(user["id"], tier=body.tier)
    return {"user": _public(db.get_user(user["id"]))}


@router.post("/api-token")
def create_api_token(user: dict = Depends(required_user)) -> dict:
    """Long-lived API token for programmatic access (Enterprise)."""
    require_feature(user, "api_access")
    token = db.issue_token(user["id"], kind="api")
    return {"api_token": token}


@router.post("/logo")
async def upload_logo(file: UploadFile = File(...),
                      user: dict = Depends(required_user)) -> dict:
    """White-label logo shown on exported PDF reports (Enterprise)."""
    require_feature(user, "white_label")
    raw = await file.read()
    if len(raw) > 1024 * 1024:
        raise HTTPException(413, "Logo exceeds 1 MB")
    if not raw[:8].startswith((b"\x89PNG", b"\xff\xd8")):
        raise HTTPException(422, "Logo must be PNG or JPEG")
    path = LOGO_DIR / f"user-{user['id']}.png"
    path.write_bytes(raw)
    db.update_user(user["id"], logo_path=str(path))
    return {"ok": True}


@router.get("/audit")
def audit(user: dict = Depends(required_user)) -> dict:
    """OT/IT compliance log (manager role), TENANT-SCOPED: a manager sees
    only their own organization's activity - never other tenants' emails."""
    if user["role"] != "manager":
        raise HTTPException(403, "Audit log is restricted to managers")
    if saas_mode():
        org = user.get("org_name") or ""
        if not org:
            raise HTTPException(403, "Audit access requires an organization")
        return {"entries": db.list_audit(org_name=org)}
    return {"entries": db.list_audit()}
