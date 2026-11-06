"""Alembic environment: schema is defined by the SQLAlchemy models; URL comes from DATABASE_URL."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from backend.app.db import Base
from backend.app.tenancy import Tenant  # noqa: F401

# Import every model so its table is registered on Base.metadata
from backend.app.audit.model import AuditEvent  # noqa: F401
from backend.app.auth.mfa_model import MFAChallenge, MFARecoveryCode, UserMFA  # noqa: F401
from backend.app.auth.passkey_model import Passkey, WebAuthnChallenge  # noqa: F401
from backend.app.auth.session import Session  # noqa: F401
from backend.app.groups.model import Group  # noqa: F401
from backend.app.groups.rules import GroupRule  # noqa: F401
from backend.app.oidc.models import SigningKey  # noqa: F401
from backend.app.users.model import User  # noqa: F401

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def _url() -> str:
    return os.environ["DATABASE_URL"]


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
