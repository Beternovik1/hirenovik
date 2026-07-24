"""baseline_jobs_schema

Baseline migration capturing the existing ``jobs`` table and its indexes.

Revision ID: 8e1f2a3b4c5d
Revises:
Create Date: 2026-07-23 00:00:00.000000 UTC

Single source of truth for the baseline
---------------------------------------
This revision transcribes the SQLAlchemy ORM schema declared in
``src/database/models.py`` (the ``Job`` model) exactly as ``Base.metadata``
would render it via ``create_all``. It is the foundation every later migration
builds on.

IMPORTANT -- applying this to the live Supabase database
--------------------------------------------------------
The production Supabase database ALREADY contains the ``jobs`` table and its
indexes: they were created historically by ``Base.metadata.create_all()``
before Alembic existed. Running ``alembic upgrade head`` there would fail
because the objects already exist.

The safe bootstrap procedure for the existing live database is to STAMP it at
the baseline revision instead of executing it:

    DATABASE_URL=<your live supabase url> alembic stamp 8e1f2a3b4c5d

``alembic stamp`` only writes the revision identifier into the
``alembic_version`` table; it executes NO DDL. After stamping, every future
migration applies cleanly on top of the existing schema.

For a FRESH/empty database (e.g. a new preview branch or local dev DB) the
baseline is applied normally, building the schema from migrations alone:

    DATABASE_URL=<empty db url> alembic upgrade head

Why a CREATE baseline instead of an empty no-op
-----------------------------------------------
A no-op (``pass``) baseline would force fresh databases to fall back on
``create_all`` and leave migrations unable to reproduce the schema on their own.
This CREATE baseline keeps migrations as the single source of DDL going forward.
The ``stamp`` procedure above handles the existing-DB case without DDL.

Why no server_default / IF NOT EXISTS
-------------------------------------
- The original model columns use Python-side ``default=`` (applied by the ORM
  at INSERT), never ``server_default=``, so the live table has no DB-level
  defaults. Mirroring that here keeps the autogenerate diff empty against the
  live DB.
- ``op.create_table`` has no native ``IF NOT EXISTS``. The ``stamp`` pattern is
  the standard Alembic bootstrap for pre-existing databases, is explicit about
  intent, and avoids masking schema drift.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "8e1f2a3b4c5d"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the baseline ``jobs`` table and indexes.

    Transcribed from ``src/database/models.py`` ``Job`` model. Column order,
    nullability, and types match ``Base.metadata`` so ``alembic revision
    --autogenerate`` produces an empty diff against a live database that was
    created by ``Base.metadata.create_all()``.
    """
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("site", sa.String(length=50), nullable=True),
        # job_url is unbounded VARCHAR; the model declares String() with no
        # length, which PostgreSQL accepts as VARCHAR with no length limit.
        sa.Column("job_url", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("company", sa.String(), nullable=False),
        sa.Column("raw_location", sa.Text(), nullable=False),
        sa.Column("country", sa.String(length=50), nullable=True),
        sa.Column("country_code", sa.String(length=5), nullable=True),
        sa.Column("state", sa.String(length=50), nullable=True),
        sa.Column("career", sa.String(length=100), nullable=True),
        sa.Column("scraped_by", sa.String(length=50), nullable=True),
        sa.Column("industry_niche", sa.String(length=50), nullable=True),
        sa.Column("is_premium", sa.Boolean(), nullable=True),
        sa.Column("job_type", sa.String(length=20), nullable=True),
        sa.Column("salary_min", sa.Numeric(), nullable=True),
        sa.Column("salary_max", sa.Numeric(), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("salary_source", sa.String(length=20), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("cleaned_description", sa.Text(), nullable=True),
        sa.Column("keywords_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("date_posted", sa.String(), nullable=True),
        sa.Column("date_scraped", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        # Unnamed unique constraint mirrors the model's Column(unique=True);
        # PostgreSQL auto-names it jobs_job_url_key, matching the live DB.
        sa.UniqueConstraint("job_url"),
    )

    op.create_index("idx_status", "jobs", ["status"], unique=False)
    op.create_index("idx_geo_type", "jobs", ["country_code", "state", "job_type"], unique=False)
    op.create_index("idx_niche_date", "jobs", ["industry_niche", "date_scraped"], unique=False)
    op.create_index("idx_career_scope", "jobs", ["career", "job_type"], unique=False)


def downgrade() -> None:
    """Drop the baseline ``jobs`` table and indexes.

    Reverses :func:`upgrade` in the inverse order objects were created. Only
    safe to run on a database whose state is fully managed by this migration
    chain; on the live Supabase database this should never be executed.
    """
    op.drop_index("idx_career_scope", table_name="jobs")
    op.drop_index("idx_niche_date", table_name="jobs")
    op.drop_index("idx_geo_type", table_name="jobs")
    op.drop_index("idx_status", table_name="jobs")
    op.drop_table("jobs")
