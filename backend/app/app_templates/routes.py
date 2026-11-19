"""Create-from-template API (IFORA-30). Reuses the existing OIDC, SAML, application and provisioning handlers (no parallel code path):
they run against a session whose commit only flushes, and the one real commit happens at the end, so a failure anywhere persists nothing."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.app_templates import registry
from backend.app.applications import routes as app_routes
from backend.app.applications.models import Application
from backend.app.auth.deps import require_admin
from backend.app.auth.stepup import require_stepup
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.oidc import client_routes as cr
from backend.app.provisioning import routes as prov_routes
from backend.app.provisioning.presets import PRESETS
from backend.app.saml import routes as saml_routes
from backend.app.users.model import User

router = APIRouter(prefix="/admin/application-templates", tags=["applications"])


class _OneTransaction:
    """Session stand-in for the duration of one create: commit() becomes flush(); everything else is the real session."""

    def __init__(self, db: Session):
        object.__setattr__(self, "_db", db)

    def commit(self):
        self._db.flush()

    def __getattr__(self, name):
        return getattr(self._db, name)


class CreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    values: Dict[str, str] = Field(default_factory=dict)


@router.get("")
def list_templates(_: User = Depends(require_admin)):
    return {"items": [registry.public_view(t) for t in registry.all_templates()]}


def _value(t: registry.Template, values: Dict[str, str], key: str) -> Optional[str]:
    v = (values.get(key) or "").strip()
    if key in {f.key for f in t.fields} and not v and key != "launch_url":
        raise HTTPException(status_code=422, detail=f"{next(f.label for f in t.fields if f.key == key)} is required")
    return v or None


@router.post("/{key}/create", status_code=201)
def create_from_template(key: str, body: CreateBody, request: Request, real_db: Session = Depends(get_db),
                         actor: User = Depends(require_admin), _step: User = Depends(require_stepup)):
    """One transaction: the application, its sign-on settings and (where the template has it) a disabled provisioning app.
    The application is created inactive so nothing signs in or provisions until the administrator finishes the checklist."""
    t = registry.get(key)
    if t is None:
        raise HTTPException(status_code=404, detail="Unknown template")
    if t.provisioning is not None and not settings.PROVISIONING_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")
    unknown = set(body.values) - {f.key for f in t.fields}
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unexpected value: {sorted(unknown)[0]}")
    vals = {f.key: _value(t, body.values, f.key) for f in t.fields}
    db = _OneTransaction(real_db)
    out: Dict[str, Any] = {"template": t.key, "checklist": list(t.checklist)}
    try:
        if t.sign_on == "oidc":
            tpl = app_routes.TEMPLATES[t.oidc.type]
            c = cr.create_client(
                cr.ClientCreate(name=body.name, description=body.description, client_type=tpl["client_type"], redirect_uris=[vals["redirect_uri"]],
                                allowed_scopes=["openid", "profile", "email"], launch_url=vals.get("launch_url"), require_assignment=True),
                request, db, actor)
            out.update(client_id=c["client_id"], client_secret=c.get("client_secret"))
            application_id = c["application_id"]
        else:
            a = app_routes.create_application(
                app_routes.AppBody(name=body.name, description=body.description, sign_on_mode=t.sign_on, status="inactive", require_assignment=True,
                                   launch_url=vals.get("launch_url")), request, db, actor)
            application_id = a["id"]
            if t.sign_on == "saml":
                saml_routes.put_saml(application_id, saml_routes.SamlBody(sp_entity_id=vals["sp_entity_id"], acs_url=vals["acs_url"], audience=vals["sp_entity_id"],
                                                                         name_id_format=t.saml.name_id_format, signing=t.saml.signing), request, db, actor)
        if t.provisioning is not None:
            preset = next(x for x in PRESETS if x["key"] == t.provisioning.preset)
            p = prov_routes.create_app(
                prov_routes.AppBody(name=body.name, description=body.description, kind=preset["kind"], base_url=t.provisioning.base_url or vals["base_url"],
                                    auth_type=preset["auth_type"], secret=vals["secret"], options=prov_routes.Options(**preset["options"]),
                                    mapping=t.provisioning.mapping, rest_config=preset.get("rest_config"), application_id=application_id),
                request, db, actor)
            out["provisioning_app_id"] = p["id"]
        app = real_db.get(Application, application_id)
        app.status = "inactive"  # disabled until the checklist is done
        real_db.flush()
    except Exception:
        real_db.rollback()
        raise
    out["application_id"] = application_id
    real_db.commit()
    return out
