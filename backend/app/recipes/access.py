"""Who may use or manage a recipe connection. A connection with no `allowed_users` list behaves as before: every
administrator can use and manage it. With a list, only those administrators (plus its creator and super admins) can
attach it to a recipe step; only the creator or a super admin can edit, rotate or delete it. Checked when a recipe is
saved, tested or published, not when a job runs (a published recipe keeps working if the list changes later)."""


def restricted(conn) -> bool:
    return bool(conn.allowed_users)


def can_use_connection(actor, conn) -> bool:
    if not restricted(conn):
        return True
    return actor.is_super_admin or actor.id == conn.created_by or actor.id in conn.allowed_users


def can_manage_connection(actor, conn) -> bool:
    if not restricted(conn):
        return True
    return actor.is_super_admin or actor.id == conn.created_by
