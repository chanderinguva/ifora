"""Who is entitled to an application: assigned directly, or a member of an assigned group."""

from typing import List, Set

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.applications.models import Application, ApplicationAssignment
from backend.app.groups.model import user_group_association as membership


def assigned_group_ids(db: Session, application_id: int) -> List[int]:
    return [g for (g,) in db.query(ApplicationAssignment.group_id).filter(
        ApplicationAssignment.application_id == application_id, ApplicationAssignment.group_id.is_not(None)).all()]


def is_entitled(db: Session, application_id: int, user_id: int) -> bool:
    if db.query(ApplicationAssignment.id).filter(
            ApplicationAssignment.application_id == application_id, ApplicationAssignment.user_id == user_id).first():
        return True
    gids = assigned_group_ids(db, application_id)
    if not gids:
        return False
    return db.execute(select(membership.c.user_id).where(membership.c.user_id == user_id, membership.c.group_id.in_(gids)).limit(1)).first() is not None


def entitled_user_ids(db: Session, application_id: int) -> Set[int]:
    ids = {u for (u,) in db.query(ApplicationAssignment.user_id).filter(
        ApplicationAssignment.application_id == application_id, ApplicationAssignment.user_id.is_not(None)).all()}
    gids = assigned_group_ids(db, application_id)
    if gids:
        ids |= {u for (u,) in db.execute(select(membership.c.user_id).where(membership.c.group_id.in_(gids))).all()}
    return ids


def entitled_application_ids(db: Session, user_id: int) -> Set[int]:
    direct = {a for (a,) in db.query(ApplicationAssignment.application_id).filter(ApplicationAssignment.user_id == user_id).all()}
    gids = [g for (g,) in db.execute(select(membership.c.group_id).where(membership.c.user_id == user_id)).all()]
    if gids:
        direct |= {a for (a,) in db.query(ApplicationAssignment.application_id).filter(ApplicationAssignment.group_id.in_(gids)).all()}
    return direct


def sign_on_denied(db: Session, client, user_id: int) -> bool:
    """True when this OIDC client belongs to an application that requires assignment and the user is not entitled
    (or the application is inactive). Clients without an application are unaffected."""
    app_id = getattr(client, "application_id", None)
    if app_id is None:
        return False
    app = db.get(Application, app_id)
    return False if app is None else application_denied(db, app, user_id)


def application_denied(db: Session, app: "Application", user_id: int) -> bool:
    if app.status != "active":
        return True
    return bool(app.require_assignment) and not is_entitled(db, app.id, user_id)


def ensure_for_client(db: Session, client, actor_id=None, launch_url=None, require_assignment=False) -> "Application":
    """Every OIDC client is an application. A client created through the OIDC client API gets one that keeps today's
    behaviour (assignment not required); create the application first to require assignment."""
    import uuid

    base = client.name.strip()[:90] or "Application"
    name, n = base, 1
    while db.query(Application.id).filter(Application.name == name).first():
        n += 1
        name = f"{base} ({n})"
    app = Application(public_id=str(uuid.uuid4()), name=name, description=client.description, sign_on_mode="oidc",
                      visible=client.client_type != "service", require_assignment=require_assignment, created_by=actor_id,
                      launch_url=None if client.client_type == "service" else launch_url)
    db.add(app)
    db.flush()
    client.application_id = app.id
    return app


def drop_for_client(db: Session, client) -> None:
    """The client is going away: remove its application unless provisioning is attached to it."""
    from backend.app.provisioning.models import ProvisioningApp

    if client.application_id is None:
        return
    app = db.get(Application, client.application_id)
    client.application_id = None
    if app is not None and not db.query(ProvisioningApp.id).filter(ProvisioningApp.application_id == app.id).first():
        db.delete(app)
    elif app is not None:
        app.sign_on_mode = "none"
        app.launch_url = None
