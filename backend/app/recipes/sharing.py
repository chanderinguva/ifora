"""Shared validation for connection sharing; all lookups are tenant scoped."""
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, Field
from backend.app.groups.model import Group
from backend.app.recipes import access
from backend.app.recipes.models import RecipeFolder


class SharingBody(BaseModel):
    sharing_scope: Literal["legacy", "organization", "folder"] | None = None
    folder_ids: list[int] | None = Field(None, max_length=100)
    use_group_ids: list[int] | None = Field(None, max_length=100)
    manage_group_ids: list[int] | None = Field(None, max_length=100)


def checked_groups(db, ids):
    ids = sorted(set(ids or []))
    if ids and {x for (x,) in db.query(Group.id).filter(Group.id.in_(ids))} != set(ids):
        raise HTTPException(422, "Choose existing groups in this organization")
    return ids


def apply_sharing(db, actor, conn, body, *, creating=False):
    # Legacy clients retain their exact behavior; the new UI explicitly opts in.
    scope = body.sharing_scope or ("legacy" if creating else conn.sharing_scope)
    if scope == "legacy":
        if not creating and conn.sharing_scope != "legacy":
            raise HTTPException(422, "A shared connection cannot revert to a legacy allow-list")
        return
    folders = sorted(set(body.folder_ids if body.folder_ids is not None else conn.folder_ids or []))
    if scope == "folder" and not folders:
        raise HTTPException(422, "Assign at least one folder")
    for fid in folders:
        f = db.get(RecipeFolder, fid)
        if f is None or not access.can_manage_folder(actor, f):
            raise HTTPException(403, "You must manage every folder assigned to this connection")
    if scope == "folder" and body.use_group_ids:
        raise HTTPException(422, "Folder connections inherit their folder's use permissions")
    conn.sharing_scope, conn.folder_ids = scope, folders
    for key in ("use_group_ids", "manage_group_ids"):
        value = getattr(body, key)
        if value is not None:
            setattr(conn, key, checked_groups(db, value))
    if scope == "folder":
        conn.use_group_ids = []
    # Only an explicit conversion replaces the legacy restriction.
    conn.allowed_users = None


def require_folder(db, actor, fid, *, manage=False):
    if fid is None:
        return
    f = db.get(RecipeFolder, fid)
    if f is None or not (access.can_manage_folder if manage else access.can_use_folder)(actor, f):
        raise HTTPException(403, "You do not have access to this folder")
