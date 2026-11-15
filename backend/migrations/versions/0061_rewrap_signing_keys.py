"""Re-encrypt OIDC and SAML signing keys under purpose-separated keys (IFORA-25).

Each private key moves from the bare `OIDC_KEY_ENCRYPTION_KEY` Fernet token to `v2:<purpose>:<token>` (see
app/keywrap.py). Rows are rewritten one at a time and only after the old value decrypted; a value that already carries
the v2 prefix is left alone, so the migration is safe to re-run. Reversible: the downgrade writes the legacy format back.
Nothing is logged; failures name the table and row id, never a value.

Revision ID: 0061
Revises: 0060
"""

import sqlalchemy as sa
from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None

TABLES = (("oidc_signing_keys", "private_pem_encrypted", "oidc"), ("saml_signing_keys", "private_key_enc", "saml"))


def _rewrite(convert) -> None:
    from backend.app import keywrap

    conn = op.get_bind()
    for table, column, purpose in TABLES:
        rows = conn.execute(sa.text(f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL")).fetchall()  # noqa: S608
        for row_id, value in rows:
            try:
                new = convert(keywrap, purpose, value)
            except keywrap.KeyWrapError as e:
                raise RuntimeError(f"cannot re-encrypt {table} id={row_id}: {e}") from None
            if new != value:
                conn.execute(sa.text(f"UPDATE {table} SET {column} = :v WHERE id = :i"), {"v": new, "i": row_id})  # noqa: S608


def _to_v2(keywrap, purpose, value):
    return value if keywrap.is_wrapped(value) else keywrap.wrap(purpose, keywrap.unwrap(purpose, value))


def _to_legacy(keywrap, purpose, value):
    return keywrap.legacy_fernet().encrypt(keywrap.unwrap(purpose, value)).decode() if keywrap.is_wrapped(value) else value


def upgrade() -> None:
    _rewrite(_to_v2)


def downgrade() -> None:
    _rewrite(_to_legacy)
