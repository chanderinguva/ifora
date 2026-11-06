#!/bin/sh
# Apply database migrations, then start the app.
set -e
cd /app

# A database created before migrations existed has the tables but no alembic_version:
# adopt it at the baseline revision instead of failing on "table already exists".
python - <<'PY'
import os
from sqlalchemy import create_engine, inspect

tables = set(inspect(create_engine(os.environ["DATABASE_URL"])).get_table_names())
if "users" in tables and "alembic_version" not in tables:
    print("entrypoint: legacy schema detected, stamping baseline 0001", flush=True)
    os.system("alembic -c backend/alembic.ini stamp 0001")
PY

alembic -c backend/alembic.ini upgrade head
exec "$@"
