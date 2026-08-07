"""SQLite-compatible partial unique index for tests.

PostgreSQL's partial unique index (``WHERE status = 'confirmed'``)
is not supported by SQLite.  For integration tests against an
in-memory SQLite database, we use a substitute:

A regular UNIQUE constraint on ``(duplicate_job_id, scope, status)``
which is stricter (blocks multiple candidates) but still validates
the core behavior — only one confirmed row per (dup, scope).

The *real* PostgreSQL migration uses the correct partial unique index.
"""
