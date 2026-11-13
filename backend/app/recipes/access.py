"""Connection authorization. Legacy restrictions stay intact until explicitly migrated."""
from sqlalchemy.orm import object_session


def group_ids(actor):
    from backend.app.groups.model import Group, user_group_association
    db = object_session(actor)
    if db is None:
        return set()
    return {g for (g,) in db.query(Group.id).join(user_group_association,
            user_group_association.c.group_id == Group.id).filter(user_group_association.c.user_id == actor.id)}


def can_use_folder(actor, folder):
    return bool(actor.is_super_admin or actor.id == folder.created_by or
                group_ids(actor) & set((folder.use_group_ids or []) + (folder.manage_group_ids or [])))


def can_manage_folder(actor, folder):
    return bool(actor.is_super_admin or actor.id == folder.created_by or
                group_ids(actor) & set(folder.manage_group_ids or []))


def restricted(conn):
    return bool(conn.allowed_users or getattr(conn, "sharing_scope", "legacy") != "legacy")


def can_manage_connection(actor, conn):
    if getattr(conn, "sharing_scope", "legacy") == "legacy":
        return not conn.allowed_users or actor.is_super_admin or actor.id == conn.created_by
    if actor.is_super_admin or group_ids(actor) & set(conn.manage_group_ids or []):
        return True
    if conn.sharing_scope == "organization":
        return actor.id == conn.created_by
    from backend.app.recipes.models import RecipeFolder
    db = object_session(actor)
    folders = list(db.query(RecipeFolder).filter(RecipeFolder.id.in_(conn.folder_ids or []))) if db else []
    # Editing a connection shared by folders affects every assigned folder.
    return bool(folders and len(folders) == len(set(conn.folder_ids or [])) and all(can_manage_folder(actor, f) for f in folders))


def can_use_connection(actor, conn):
    if getattr(conn, "sharing_scope", "legacy") == "legacy":
        return not conn.allowed_users or actor.is_super_admin or actor.id == conn.created_by or actor.id in conn.allowed_users
    if can_manage_connection(actor, conn):
        return True
    groups = group_ids(actor)
    if conn.sharing_scope == "organization":
        return not conn.use_group_ids or bool(groups & set(conn.use_group_ids))
    from backend.app.recipes.models import RecipeFolder
    db = object_session(actor)
    return bool(db and any(can_use_folder(actor, f) for f in db.query(RecipeFolder).filter(RecipeFolder.id.in_(conn.folder_ids or []))))


def available_in_folder(conn, folder_id):
    return conn.sharing_scope == "legacy" or (conn.sharing_scope == "organization" and not conn.folder_ids) or folder_id in (conn.folder_ids or [])


def can_use_in_recipe(actor, conn, folder_id):
    if not can_use_connection(actor, conn) or not available_in_folder(conn, folder_id):
        return False
    if conn.sharing_scope != "folder":
        return True
    from backend.app.recipes.models import RecipeFolder
    db = object_session(actor)
    f = db.get(RecipeFolder, folder_id) if db and folder_id else None
    return bool(f and can_use_folder(actor, f))
