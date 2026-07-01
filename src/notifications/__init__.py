"""Notifications package: alert profiles, deterministic matching, scoring, digest.

This package is the foundation for the alert system. It provides subscriber
alert profiles (:mod:`notifications.profiles`), a pure deterministic binary
matcher (:mod:`notifications.matcher`), a CV-informed scorer with human-readable
reasons (:mod:`notifications.scoring`), and a deterministic digest selector that
composes a serializable payload of the top jobs to send
(:mod:`notifications.digest`). Email sending, notification logging, and HTML
rendering are intentionally out of scope for these slices.

The package itself stays free of database/SQLAlchemy imports so importing
``notifications`` never pulls in the ORM. The DB-facing digest retrieval lives
in :mod:`notifications.digest_repository`, imported explicitly by callers that
need it.
"""
from __future__ import annotations

from notifications.digest import (
    DIGEST_DEFAULT_FRESHNESS_DAYS,
    DIGEST_DEFAULT_LIMIT,
    DIGEST_NICHE,
    DIGEST_PROFILE_NAME,
    DigestJob,
    DigestPayload,
    payload_to_dict,
    select_digest,
)
from notifications.matcher import match_job, match_jobs
from notifications.profiles import (
    ALERT_PROFILES,
    INDUSTRIAL_IRAPUATO_BAJIO_PROFILE,
    AlertProfile,
    LocationTier,
    RoleGroup,
    get_alert_profile,
)
from notifications.scoring import score_job, score_jobs

__all__ = [
    "AlertProfile",
    "ALERT_PROFILES",
    "DIGEST_DEFAULT_FRESHNESS_DAYS",
    "DIGEST_DEFAULT_LIMIT",
    "DIGEST_NICHE",
    "DIGEST_PROFILE_NAME",
    "DigestJob",
    "DigestPayload",
    "INDUSTRIAL_IRAPUATO_BAJIO_PROFILE",
    "LocationTier",
    "RoleGroup",
    "get_alert_profile",
    "match_job",
    "match_jobs",
    "payload_to_dict",
    "score_job",
    "score_jobs",
    "select_digest",
]
