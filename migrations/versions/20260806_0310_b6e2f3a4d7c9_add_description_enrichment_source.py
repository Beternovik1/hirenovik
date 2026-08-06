"""add_description_enrichment_source

Add ``description_enrichment_source`` column to the ``jobs`` table
to track whether ``cleaned_description`` came from a live detail-page
fetch (``detail_page``) or was prepared from the stored raw description
(``raw_description``).

Revision ID: b6e2f3a4d7c9
Revises: a5d1e2f3b6c8
Create Date: 2026-08-06 03:10:00.000000 UTC

Column contract
---------------

``description_enrichment_source`` — ``VARCHAR(20)``, nullable, no default.

Values:
- ``NULL`` — never enriched/prepared (the existing state)
- ``"raw_description"`` — cleaned from stored raw description
  (prepared by the Slice 3.5 ``DescriptionPreparer``)
- ``"detail_page"`` — fetched from live job-board detail page
  (produced by ``run_local_enrichment_pipeline``)

This column is intentionally separate from ``skill_extractor_version``
and ``skills_extracted_at`` because description enrichment and skill
extraction are independent pipelines that may run at different times
with different provenance.

No index is added: the column is narrow (20 bytes max) and will be
queried with equality predicates (``='raw_description'``) during
controlled analysis, not full-table scans.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6e2f3a4d7c9"
down_revision: str | None = "a5d1e2f3b6c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "description_enrichment_source",
            sa.String(length=20),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("jobs", "description_enrichment_source")
