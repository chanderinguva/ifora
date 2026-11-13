"""Recipe engine tables (ADR 008). All tenant-owned; jobs copy the definition they run so versions stay immutable."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB

from backend.app.db import Base
from backend.app.tenancy import TenantOwned


def _now():
    return datetime.now(timezone.utc)


class Recipe(TenantOwned, Base):
    __tablename__ = "recipes"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_recipes_tenant_name"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    public_id = Column(String(32), nullable=False, unique=True)  # webhook URL component (random, unguessable)
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    enabled = Column(Boolean, nullable=False, default=False)
    draft = Column(JSONB, nullable=False)
    published_version = Column(Integer, nullable=True)
    published_trigger_type = Column(String(40), nullable=True, index=True)
    webhook_secret_enc = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # may publish/enable/run/delete and grant access
    editors = Column(JSONB, nullable=False, default=list, server_default="[]")  # admin user ids who may edit the draft and dry-run it
    folder_id = Column(Integer, ForeignKey("recipe_folders.id", ondelete="RESTRICT"), nullable=True, index=True)
    rate_limit_per_hour = Column(Integer, nullable=True)  # live jobs started per rolling hour (None = server default)
    throttled_count = Column(Integer, nullable=False, default=0, server_default="0")
    last_throttled_at = Column(DateTime(timezone=True), nullable=True)
    last_alert_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class RecipeVersion(TenantOwned, Base):
    """Immutable once written: there is no update or delete path."""

    __tablename__ = "recipe_versions"
    __table_args__ = (UniqueConstraint("recipe_id", "version", name="uq_recipe_versions_recipe_version"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    definition = Column(JSONB, nullable=False)
    published_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class RecipeConnection(TenantOwned, Base):
    __tablename__ = "recipe_connections"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_recipe_connections_tenant_name"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    kind = Column(String(32), nullable=False)  # bearer | header | oauth2_client_credentials | slack_webhook
    header_name = Column(String(100), nullable=True)
    allowed_host = Column(String(255), nullable=False)
    allowed_paths = Column(JSONB, nullable=True)  # path prefixes the credential may be sent to (None = any path on the host)
    client_id = Column(String(255), nullable=True)  # oauth2_client_credentials
    token_url = Column(String(2000), nullable=True)  # oauth2_client_credentials (must be on allowed_host)
    scope = Column(String(500), nullable=True)
    allowed_users = Column(JSONB, nullable=True)  # admin ids that may use it in recipes; None/empty = every administrator
    secret_enc = Column(Text, nullable=False)  # bearer/header secret, OAuth2 client secret, Slack webhook URL, or (connectors) encrypted JSON of the secret fields
    connector_id = Column(String(32), nullable=True)  # a pre-built connector (ADR 026); kind is then "connector"
    connector_version = Column(Integer, nullable=True)
    config = Column(JSONB, nullable=True)  # the connector's non-secret settings (organisation, account name, ...)
    sharing_scope = Column(String(16), nullable=False, default="legacy", server_default="legacy")
    folder_ids = Column(JSONB, nullable=False, default=list, server_default="[]")
    use_group_ids = Column(JSONB, nullable=False, default=list, server_default="[]")
    manage_group_ids = Column(JSONB, nullable=False, default=list, server_default="[]")
    granted_scopes = Column(JSONB, nullable=True)  # None = unknown; [] = verified empty
    scopes_checked_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class RecipeFolder(TenantOwned, Base):
    """Flat automation folders; group roles never grant access to secret values."""
    __tablename__ = "recipe_folders"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_recipe_folders_name"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    use_group_ids = Column(JSONB, nullable=False, default=list, server_default="[]")
    manage_group_ids = Column(JSONB, nullable=False, default=list, server_default="[]")
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class ConnectionOAuthState(TenantOwned, Base):
    __tablename__ = "connection_oauth_states"
    id = Column(String(64), primary_key=True)  # SHA256 of browser state
    connection_id = Column(Integer, ForeignKey("recipe_connections.id", ondelete="CASCADE"), nullable=False)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    verifier_enc = Column(Text, nullable=False)
    connection_updated_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)


class RecipeOutbox(TenantOwned, Base):
    __tablename__ = "recipe_outbox"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(40), nullable=False)
    payload = Column(JSONB, nullable=False)
    depth = Column(Integer, nullable=False, default=0)
    origin_recipe_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    dispatched_at = Column(DateTime(timezone=True), nullable=True, index=True)


class RecipeJob(TenantOwned, Base):
    __tablename__ = "recipe_jobs"
    __table_args__ = (UniqueConstraint("recipe_id", "idempotency_key", name="uq_recipe_jobs_idempotency"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=True)  # NULL for dry runs of the draft
    mode = Column(String(10), nullable=False, default="live")  # live | dry_run
    status = Column(String(12), nullable=False, default="queued", index=True)  # queued running succeeded failed cancelled
    definition = Column(JSONB, nullable=False)
    trigger = Column(JSONB, nullable=False)
    trigger_type = Column(String(40), nullable=False)
    event_id = Column(Integer, nullable=True)
    idempotency_key = Column(String(128), nullable=False)
    depth = Column(Integer, nullable=False, default=0)
    pc = Column(Integer, nullable=False, default=0)
    in_handler = Column(Boolean, nullable=False, default=False, server_default="false")  # running the definition's on_error steps
    cancel_requested = Column(Boolean, nullable=False, default=False, server_default="false")
    rerun_of = Column(Integer, nullable=True)  # the job this one re-runs
    parent_job_id = Column(Integer, nullable=True, index=True)  # the job whose Call recipe step started this one
    call_chain = Column(JSONB, nullable=True)  # ids of the recipes above this job in the call chain (recursion guard)
    approval = Column(JSONB, nullable=True)  # {step_id, message, requested_at, expires_at, decision, decided_by} while/after waiting
    paused_seconds = Column(Integer, nullable=False, default=0, server_default="0")  # time spent waiting; not counted against the runtime cap
    executed_steps = Column(Integer, nullable=False, default=0)
    attempt = Column(Integer, nullable=False, default=0)
    step_outputs = Column(JSONB, nullable=False, default=dict)
    next_run_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class RecipeJobStep(TenantOwned, Base):
    """One row per step attempt (the per-step history)."""

    __tablename__ = "recipe_job_steps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("recipe_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    step_id = Column(String(64), nullable=False)
    type = Column(String(30), nullable=False)
    status = Column(String(12), nullable=False)  # succeeded | failed | retrying
    attempt = Column(Integer, nullable=False, default=1)
    input = Column(JSONB, nullable=True)
    output = Column(JSONB, nullable=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class LookupTable(TenantOwned, Base):
    """A small admin-owned table recipes can read (and, unless admin-managed, write). ADR 021 section 2."""

    __tablename__ = "lookup_tables"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_lookup_tables_tenant_name"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(40), nullable=False)  # how recipes refer to it; never renamed
    description = Column(String(300), nullable=True)
    columns = Column(JSONB, nullable=False)  # [{"name": "department", "type": "text|number|boolean|date"}]
    key_column = Column(String(40), nullable=True)  # values are unique and recipes can upsert / delete by it
    admin_managed = Column(Boolean, nullable=False, default=True, server_default="true")  # True: only administrators write rows, reads are trusted
    row_count = Column(Integer, nullable=False, default=0, server_default="0")
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class LookupRow(TenantOwned, Base):
    __tablename__ = "lookup_rows"
    __table_args__ = (Index("uq_lookup_rows_key", "table_id", "key_value", unique=True, postgresql_where=text("key_value IS NOT NULL")),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    table_id = Column(Integer, ForeignKey("lookup_tables.id", ondelete="CASCADE"), nullable=False, index=True)
    data = Column(JSONB, nullable=False)
    key_value = Column(String(500), nullable=True)  # the key column's value as text (null for tables without a key)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now)
