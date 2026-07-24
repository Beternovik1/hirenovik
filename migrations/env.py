"""Alembic migration environment for the Hirenovik Supabase PostgreSQL database.

This module wires Alembic to the existing SQLAlchemy ORM models declared in
``database.models``. Per CONVENTIONS.md the connection URL is resolved from the
environment through ``shared.config.get_database_url()`` (single source of
truth) and is never read from ``alembic.ini`` so no secret is stored on disk.

Slice 1 (this file) only provides the migration foundation. It performs no
schema changes and never connects to the database unless an online migration
command explicitly requests it.
"""

from __future__ import annotations

import logging
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the repo root and the ``src/`` package layout importable so the same
# absolute imports the application uses (``database.models``, ``shared.config``)
# resolve inside the Alembic process regardless of where ``alembic`` is invoked.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _REPO_ROOT / "src"
for _path in (str(_REPO_ROOT), str(_SRC_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from database.models import Base  # noqa: E402  (path setup must precede import)
from shared.config import get_database_url  # noqa: E402

# this is the Alembic Config object giving access to .ini values
config = context.config

# Interpret the config file for Python logging unless running a command that
# only prints (e.g. ``alembic list``) where logging noise is undesirable.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")

# Target metadata drives autogenerate diffs. Importing the model module above
# registers every ORM table on Base.metadata, so future ``notification_log``
# tables (added in a later slice) only need to be declared in database.models to
# be picked up automatically.
target_metadata = Base.metadata


def _resolve_url() -> str:
    """Return the DB URL from the single source of truth, never logging it.

    If the environment is not configured we fail fast with an actionable message
    rather than letting SQLAlchemy emit a cryptic connection error later. The
    URL itself is intentionally NOT logged to avoid writing a secret to stderr.
    """
    try:
        return get_database_url()
    except ValueError:
        logger.error("DATABASE_URL is not set; configure it before running migrations.")
        raise


def run_migrations_offline() -> None:
    """Render migrations as SQL scripts without a live DB connection.

    Used by ``alembic upgrade <rev> --sql``. The URL is injected programmatically
    so the offline output can be generated without touching alembic.ini.
    """
    url = _resolve_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection.

    The URL is loaded from the environment at call time and injected into the
    config dict read from ``alembic.ini`` (whose ``sqlalchemy.url`` is empty by
    design), so the running process never sees a secret on disk.
    """
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _resolve_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        # A NullPool avoids holding connections open between migration steps; the
        # migration process is short-lived and never reuses pooled connections.
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # compare_type catches column type drift on autogenerate (e.g. String
            # vs Text changes), which the default Alembic template would miss.
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
