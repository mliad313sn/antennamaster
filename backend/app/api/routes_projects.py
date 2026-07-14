"""Project workspaces: save / list / duplicate / share simulation projects."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..services.saas import db
from ..services.saas.tiers import PROJECT_QUOTA
from .routes_auth import required_user

router = APIRouter(prefix="/api/projects", tags=["saas"])


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field("coverage", max_length=40)
    data: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    data: dict[str, Any] | None = None


def _quota_check(user: dict) -> None:
    quota = PROJECT_QUOTA.get(user["tier"])
    if quota is not None and db.count_projects(user["id"]) >= quota:
        raise HTTPException(
            402, f"The {user['tier']} plan allows {quota} saved projects. "
                 "Upgrade for more workspaces.")


@router.post("")
def create(body: ProjectIn, user: dict = Depends(required_user)) -> dict:
    _quota_check(user)
    project = db.create_project(user["id"], body.name, body.kind, body.data)
    db.log_action(user["id"], "project_created", body.name)
    return {"project": project}


@router.get("")
def list_all(user: dict = Depends(required_user)) -> dict:
    return {"projects": db.list_projects(user["id"])}


@router.get("/shared/{token}")
def get_shared(token: str) -> dict:
    """Read-only access to a shared project (no login needed - the token IS
    the capability)."""
    project = db.get_project_by_share_token(token)
    if project is None:
        raise HTTPException(404, "Unknown share link")
    project.pop("user_id", None)
    # Never echo the capability token back into an unauthenticated response
    # (it would end up in logs/referrers of anyone the link reaches).
    project.pop("share_token", None)
    return {"project": project}


@router.get("/{project_id}")
def get_one(project_id: int, user: dict = Depends(required_user)) -> dict:
    project = _owned(project_id, user)
    return {"project": project}


@router.put("/{project_id}")
def update(project_id: int, body: ProjectUpdate,
           user: dict = Depends(required_user)) -> dict:
    _owned(project_id, user)
    db.update_project(project_id, name=body.name, data=body.data)
    return {"project": db.get_project(project_id)}


@router.post("/{project_id}/duplicate")
def duplicate(project_id: int, user: dict = Depends(required_user)) -> dict:
    src = _owned(project_id, user)
    _quota_check(user)
    copy = db.create_project(user["id"], f"{src['name']} (copy)",
                             src["kind"], src["data"])
    db.log_action(user["id"], "project_duplicated", src["name"])
    return {"project": copy}


@router.post("/{project_id}/share")
def share(project_id: int, user: dict = Depends(required_user)) -> dict:
    _owned(project_id, user)
    token = db.share_project(project_id)
    db.log_action(user["id"], "project_shared", str(project_id))
    return {"share_token": token, "url": f"/api/projects/shared/{token}"}


@router.delete("/{project_id}")
def delete(project_id: int, user: dict = Depends(required_user)) -> dict:
    _owned(project_id, user)
    db.delete_project(project_id)
    return {"deleted": project_id}


def _owned(project_id: int, user: dict) -> dict:
    project = db.get_project(project_id)
    if project is None or project["user_id"] != user["id"]:
        raise HTTPException(404, "Project not found")
    return project
