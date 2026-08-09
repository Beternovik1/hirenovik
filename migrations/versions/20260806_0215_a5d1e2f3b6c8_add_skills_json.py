"""add_skills_json

Add ``skills_json``, ``skill_extractor_version``, and ``skills_extracted_at``
columns to the ``jobs`` table for per-listing canonical skill extraction.

Revision ID: a5d1e2f3b6c8
Revises: c4b2a1d3e9f7
Create Date: 2026-08-06 02:15:00.000000 UTC

Column contract
---------------

``skills_json`` — PostgreSQL JSONB, nullable, no default.

Stores a deterministic array of canonical skill keys produced by the
standalone :class:`~src.nlp.skill_extractor.SkillExtractor`. Examples::

    ["aws", "docker", "python", "sql"]
    ["sap", "sap_mm", "sap_wm"]

**NULL semantics (enforced by application code, not by this migration):**

- ``NULL`` — the row has not been processed by the skill extractor. This is the
  initial state for every existing and newly scraped row. A later backfill
  slice (Slice 3) will scan for ``skills_json IS NULL AND
  cleaned_description IS NOT NULL`` to determine which rows need extraction.

- ``[]`` (empty JSON array) — the row was processed successfully but no known
  canonical skills were detected in the description. This is distinct from
  ``NULL`` because it means "we looked and found nothing", not "we never
  looked". Consumers (e.g. the analytics endpoint in Slice 5) can distinguish
  "unprocessed" from "processed — zero skills" and compute accurate coverage
  metrics.

- ``["python", "sql"]`` — normal extraction result.

The column is deliberately NOT given a ``NOT NULL DEFAULT '[]'`` because
that would make every existing row appear as if it had been processed with
zero matches, corrupting coverage calculations. We want ``NULL`` to mean
"not yet touched" without needing a separate status column.

``skill_extractor_version`` — ``VARCHAR(32)``, nullable, no default.

Records the taxonomy version (from :attr:`~SkillTaxonomy.version`) that was
active at extraction time. This allows future backfills to detect rows
extracted with an outdated taxonomy and selectively reprocess them.

``skills_extracted_at`` — ``TIMESTAMP WITH TIME ZONE``, nullable, no default.

When the extraction was performed (application-supplied, NOT a server
default). Together with ``skill_extractor_version``, provides the minimum
audit trail needed for version-aware reprocessing without a dedicated log
table.

Why these are separate from ``keywords_json``
---------------------------------------------

The existing ``keywords_json`` column stores BERTopic topic metadata::

    {"topic_id": 4, "topic_keywords": ["cloud", "aws", "infrastructure"]}

Topic keywords are statistical representations of a document cluster —
they describe the *topic*, not the individual *listing*. If a listing
belongs to topic 4, that does not mean the listing explicitly mentions
"cloud", "aws", or "infrastructure".

``skills_json`` contains deterministic listing-level evidence: these
canonical skill keys were literally detected in this row's
``cleaned_description`` by the pattern matcher.

Mixing both concepts in one column would require every consumer to parse
the object shape, infer the source, and apply different semantics — fragile
and un-SQL.

No index is added at this stage because:

- The backfill (Slice 3) scans by ``skills_json IS NULL``, which is a
  predicate on a nullable column with no index benefit from a B-tree on a
  JSONB value.
- The analytics endpoint (Slice 5) aggregates across the whole table, so a
  sequential scan is unavoidable.
- We may add a partial index later (e.g. ``WHERE skills_json IS NULL``) if
  incremental enrichment performance warrants it, but that belongs in a
  separate migration with real-world profiling evidence.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a5d1e2f3b6c8"
down_revision: str | None = "c4b2a1d3e9f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add skills_json, skill_extractor_version, and skills_extracted_at to jobs."""
    op.add_column(
        "jobs",
        sa.Column(
            "skills_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "skill_extractor_version",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "skills_extracted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove the three skill-extraction columns from jobs."""
    op.drop_column("jobs", "skills_extracted_at")
    op.drop_column("jobs", "skill_extractor_version")
    op.drop_column("jobs", "skills_json")
