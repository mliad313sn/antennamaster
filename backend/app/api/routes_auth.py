"""Authentication, accounts, tiers, audit and white-label branding."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from pydantic import BaseModel, EmailStr, Field

from ..config import DATA_DIR
from ..services.saas import db
from ..services.saas.tiers import TIER_INFO, require_feature

router = APIRouter(prefix="/api/auth", tags=["saas"])

LOGO_DIR = DATA_DIR / "logos"
LOGO_DIR.mkdir(parents=True, exist_ok=True)


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
def register(body: RegisterIn) -> dict:
    if db.get_user_by_email(body.email):
        raise HTTPException(409, "An account with this email already exists")
    user = db.create_user(body.email, body.password, name=body.name,
                          role=body.role, org_name=body.org_name)
    token = db.issue_token(user["id"])
    db.log_action(user["id"], "register", body.role)
    return {"token": token, "user": _public(user)}


@router.post("/login")
def login(body: LoginIn) -> dict:
    user = db.get_user_by_email(body.email)
    if user is None or not db.verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    token = db.issue_token(user["id"])
    db.log_action(user["id"], "login")
    return {"token": token, "user": _public(user)}


@router.get("/me")
def me(user: dict = Depends(required_user)) -> dict:
    return {"user": _public(user)}


@router.get("/tiers")
def tiers() -> dict:
    """Public plan matrix for the pricing/upgrade UI."""
    return {"tiers": TIER_INFO}


@router.post("/tier")
def set_tier(body: TierIn, user: dict = Depends(required_user)) -> dict:
    """Self-serve plan change (in production this sits behind the billing
    provider's webhook; the entitlement plumbing is identical)."""
    db.update_user(user["id"], tier=body.tier)
    db.log_action(user["id"], "tier_change", body.tier)
    return {"user": _public(db.get_user(user["id"]))}


@router.post("/api-token")
def create_api_token(user: dict = Depends(required_user)) -> dict:
    """Long-lived API token for programmatic access (Enterprise)."""
    require_feature(user, "api_access")
    token = db.issue_token(user["id"], kind="api")
    db.log_action(user["id"], "api_token_issued")
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
    db.log_action(user["id"], "logo_uploaded")
    return {"ok": True}


@router.get("/audit")
def audit(user: dict = Depends(required_user)) -> dict:
    """OT/IT compliance log (manager role)."""
    if user["role"] != "manager":
        raise HTTPException(403, "Audit log is restricted to managers")
    return {"entries": db.list_audit()}
