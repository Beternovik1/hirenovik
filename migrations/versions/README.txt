# Migration versions directory.
#
# Generated migration scripts land here via ``alembic revision``. Slice 1 ships
# this folder empty: the initial baseline migration (capturing the existing
# ``jobs`` schema) and the later ``notification_log`` table are intentional
# follow-up slices that the maintainer runs against the live Supabase DB.