#!/usr/bin/env python3
"""Re-encrypt connection/webhook secrets with the configured provider, one row at a time.

Dry-run by default. Run in the API container with its environment. Keep old
Fernet keys/OpenBao available until backups containing old ciphertext expire.
Never prints plaintext or ciphertext. No credentials are rotated at providers.
"""
import argparse
from backend.app.recipes import crypto
from backend.app.recipes.models import Recipe, RecipeConnection
from backend.app.tenancy import Tenant, tenant_session, unscoped
from backend.app.db import SessionLocal


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tenant", default="default")
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    with SessionLocal() as db:
        with unscoped(db):
            tenant = db.query(Tenant).filter(Tenant.slug == args.tenant).one()
            tenant_id = tenant.id
    checked = changed = 0
    for model, field in ((RecipeConnection, "secret_enc"), (Recipe, "webhook_secret_enc")):
        with tenant_session(tenant_id) as db:
            ids = [r for (r,) in db.query(model.id).filter(getattr(model, field).isnot(None))]
        for rid in ids:
            with tenant_session(tenant_id) as db:
                row = db.query(model).filter(model.id == rid).with_for_update().one()
                plain = crypto.decrypt(getattr(row, field))
                checked += 1
                if args.apply:
                    replacement = crypto.encrypt(plain)
                    if crypto.decrypt(replacement) != plain:
                        raise RuntimeError("Re-encryption verification failed")
                    setattr(row, field, replacement)
                    db.commit()
                    changed += 1
    print(f"Verified {checked} encrypted records; re-encrypted {changed}.")
    if not args.apply:
        print("Dry run only. Back up the database and recovery keys before using --apply.")


if __name__ == "__main__":
    main()
