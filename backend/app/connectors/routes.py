"""Admin API for pre-built connectors (ADR 026): the catalog, creating a connection for a connector, and testing it. Area: automation."""

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.audit.model import AuditAction
from backend.app.audit.service import record
from backend.app.auth.deps import require_admin
from backend.app.config import settings
from backend.app.connectors import engine, registry
from backend.app.db import get_db
from backend.app.recipes import access, actions, crypto
from backend.app.recipes.sharing import SharingBody, apply_sharing
from backend.app.recipes.http_client import EgressPolicy
from backend.app.recipes.models import RecipeConnection
from backend.app.users.model import User


def _enabled():
    if not settings.RECIPES_ENABLED:
        raise HTTPException(status_code=404, detail="Recipes are not enabled")


router = APIRouter(prefix="/admin/connectors", tags=["connectors"], dependencies=[Depends(_enabled)])
tests_router = APIRouter(prefix="/admin/recipe-connections", tags=["connectors"], dependencies=[Depends(_enabled)])


class ConnectorConnectionBody(SharingBody):
    name: str = Field(..., min_length=1, max_length=100)
    config: Dict[str, str] = Field(default_factory=dict, max_length=8)    # the non-secret fields of the connector's Connect form
    secrets: Dict[str, str] = Field(default_factory=dict, max_length=8)   # the secret fields (write-only: never returned)
    allowed_users: Optional[List[int]] = Field(None, max_length=50)       # admin ids; empty/None = every administrator


def _need_key():
    if not crypto.available():
        raise HTTPException(status_code=409, detail="Connections are not available: RECIPE_ENCRYPTION_KEY is not configured")


def _connector(connector_id: str):
    c = registry.get(connector_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Unknown connector")
    return c


@router.get("")
def catalog(_: User = Depends(require_admin)):
    return {"items": [registry.public_view(c) for c in registry.all_connectors()]}


@router.get("/{connector_id}")
def one(connector_id: str, _: User = Depends(require_admin)):
    return registry.public_view(_connector(connector_id))


@router.post("/{connector_id}/connections", status_code=201)
def create_connection(connector_id: str, body: ConnectorConnectionBody, request: Request, db: Session = Depends(get_db),
                      actor: User = Depends(require_admin)):
    from backend.app.recipes.routes import _acl_ids, _conn_dict

    _need_key()
    c = _connector(connector_id)
    try:
        config, secrets = engine.validate_config(c, body.config, body.secrets)
        host = engine.resolve_host(c, config)
    except engine.ConnectorError as e:
        raise HTTPException(status_code=422, detail=e.message)
    conn = RecipeConnection(name=body.name.strip(), kind="connector", allowed_host=host, connector_id=c.id, connector_version=c.version,
                            config=config, secret_enc=crypto.encrypt(json.dumps(secrets)), created_by=actor.id,
                            allowed_users=_acl_ids(db, body.allowed_users))
    apply_sharing(db, actor, conn, body, creating=True)
    db.add(conn)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Connection name already in use")
    record(db, AuditAction.RECIPE_CONNECTION_CREATED, request, actor, conn.id, "recipe_connection",
           {"name": conn.name, "host": host, "connector": c.id})
    db.commit()
    return _conn_dict(conn, actor)


@router.put("/{connector_id}/connections/{cid}")
def update_connection(connector_id: str, cid: int, body: ConnectorConnectionBody, request: Request, db: Session = Depends(get_db),
                      actor: User = Depends(require_admin)):
    """Change a connector connection. Leave a secret field out to keep the stored value; send it to rotate it."""
    from backend.app.recipes.routes import _acl_ids, _conn_dict

    _need_key()
    c = _connector(connector_id)
    conn = db.get(RecipeConnection, cid)
    if conn is None or conn.connector_id != c.id:
        raise HTTPException(status_code=404, detail="Connection not found")
    if not access.can_manage_connection(actor, conn):
        raise HTTPException(status_code=403, detail="Only the creator of this connection or a super admin can change it")
    try:
        config, secrets = engine.validate_config(c, body.config, body.secrets, partial_secrets=True)
        host = engine.resolve_host(c, config)
        if host != conn.allowed_host and {f.key for f in c.auth.fields if f.secret} - set(secrets):
            raise engine.ConnectorError("Re-enter every credential when changing the service host")
    except engine.ConnectorError as e:
        raise HTTPException(status_code=422, detail=e.message)
    if secrets:
        try:
            current = json.loads(crypto.decrypt(conn.secret_enc))
        except (ValueError, crypto.RecipeKeyError):
            current = {}
        merged = {**current, **secrets}
        if {f.key for f in c.auth.fields if f.secret} - set(merged):
            raise HTTPException(status_code=422, detail="Enter every secret field again")
        conn.secret_enc = crypto.encrypt(json.dumps(merged))
    conn.name, conn.config, conn.allowed_host, conn.connector_version = body.name.strip(), config, host, c.version
    if body.allowed_users is not None:
        conn.allowed_users = _acl_ids(db, body.allowed_users)
    apply_sharing(db, actor, conn, body)
    if secrets:
        conn.granted_scopes, conn.scopes_checked_at = None, None
    conn.updated_at = datetime.now(timezone.utc)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Connection name already in use")
    record(db, AuditAction.RECIPE_CONNECTION_UPDATED, request, actor, conn.id, "recipe_connection",
           {"name": conn.name, "secret_rotated": bool(secrets), "connector": c.id, "restricted": bool(conn.allowed_users)})
    db.commit()
    return _conn_dict(conn, actor)


@tests_router.post("/{cid}/test")
def test_connection(cid: int, request: Request, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    """Run the connector's test request with the stored credentials. Always answers 200 with {ok, message}; the audit log records the attempt."""
    _need_key()
    conn = db.get(RecipeConnection, cid)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    if not conn.connector_id:
        raise HTTPException(status_code=409, detail="Only connector connections can be tested here")
    c = registry.get(conn.connector_id)
    if c is None:
        raise HTTPException(status_code=409, detail="This connector is no longer available")
    if not access.can_use_connection(actor, conn):
        raise HTTPException(status_code=403, detail="You are not allowed to use this connection")
    try:
        config, _ = engine.validate_config(c, conn.config or {}, {}, partial_secrets=True)
        secrets = json.loads(crypto.decrypt(conn.secret_enc))
        ok, status, message = engine.check_connection(
            c, config, secrets, policy=actions.http_overrides.get("policy") or EgressPolicy.from_settings(),
            resolver=actions.http_overrides.get("resolver"), transport=actions.http_overrides.get("transport"),
            scope_sink=lambda scopes: setattr(conn, "granted_scopes", scopes))
        conn.scopes_checked_at = datetime.now(timezone.utc) if ok and conn.granted_scopes is not None else None
        if not ok:
            conn.granted_scopes = None
    except (engine.ConnectorError, ValueError, TypeError, crypto.RecipeKeyError):
        ok, status, message = False, None, "The saved connection is damaged; edit it and enter the secret again."
    record(db, AuditAction.RECIPE_CONNECTION_TESTED, request, actor, conn.id, "recipe_connection",
           {"name": conn.name, "connector": c.id, "ok": ok, "status": status})
    db.commit()
    return {"ok": ok, "status_code": status, "message": message}
