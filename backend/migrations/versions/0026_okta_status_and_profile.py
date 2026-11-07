"""Okta-style user statuses; Okta base profile attribute names

inactive -> deprovisioned, pending_activation -> provisioned. Profile keys phone -> primary_phone and
employee_id -> employee_number (catalog rows, users' stored values and group-rule conditions); location and bio stay
as ordinary custom attributes. Missing Okta built-ins are added lazily by profiles.catalog.ensure_defaults.

Revision ID: 0026
Revises: 0025
"""
import json

from alembic import op
import sqlalchemy as sa

revision = '0026'
down_revision = '0025'
branch_labels = None
depends_on = None

RENAMES = {"phone": "primary_phone", "employee_id": "employee_number"}


def _rename(d: dict, mapping: dict) -> dict:
    return {mapping.get(k, k): v for k, v in d.items()}


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE users SET status='deprovisioned' WHERE status='inactive'"))
    conn.execute(sa.text("UPDATE users SET status='provisioned' WHERE status='pending_activation'"))
    conn.execute(sa.text("UPDATE profile_attributes SET built_in=false WHERE key IN ('location','bio')"))
    for old, new in RENAMES.items():
        # skip a tenant that already has both (would violate the unique key)
        conn.execute(sa.text(
            "UPDATE profile_attributes SET key=:new WHERE key=:old AND NOT EXISTS ("
            "SELECT 1 FROM profile_attributes p2 WHERE p2.tenant_id=profile_attributes.tenant_id AND p2.key=:new)"), {"old": old, "new": new})
    conn.execute(sa.text("UPDATE profile_attributes SET display_name='Primary phone' WHERE key='primary_phone' AND display_name='Phone'"))
    conn.execute(sa.text("UPDATE profile_attributes SET display_name='Employee number' WHERE key='employee_number' AND display_name='Employee ID'"))
    for uid, raw in conn.execute(sa.text("SELECT id, profile_attributes FROM users WHERE profile_attributes IS NOT NULL")).all():
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict) and any(k in data for k in RENAMES):
            conn.execute(sa.text("UPDATE users SET profile_attributes=:p WHERE id=:i"), {"p": json.dumps(_rename(data, RENAMES)), "i": uid})
    for rid, conds in conn.execute(sa.text("SELECT id, conditions FROM group_rules")).all():
        conds = json.loads(conds) if isinstance(conds, str) else conds
        if any(isinstance(c, dict) and c.get("attribute") in RENAMES for c in conds or []):
            for c in conds:
                c["attribute"] = RENAMES.get(c.get("attribute"), c.get("attribute"))
            conn.execute(sa.text("UPDATE group_rules SET conditions=CAST(:c AS jsonb) WHERE id=:i"), {"c": json.dumps(conds), "i": rid})


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE users SET status='inactive' WHERE status IN ('deprovisioned','suspended','staged','recovery','password_expired','locked_out')"))
    conn.execute(sa.text("UPDATE users SET status='active' WHERE status='provisioned'"))
