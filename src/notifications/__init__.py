"""Notifications package: alert profiles, deterministic matching, and scoring.

This package is the foundation for the alert system. It provides subscriber
alert profiles (:mod:`notifications.profiles`), a pure deterministic binary
matcher (:mod:`notifications.matcher`), and a CV-informed scorer with
human-readable reasons (:mod:`notifications.scoring`). Email sending,
notification logging, and database persistence are intentionally out of scope
for this foundation slice.
"""
from __future__ import annotations

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
    "INDUSTRIAL_IRAPUATO_BAJIO_PROFILE",
    "LocationTier",
    "RoleGroup",
    "get_alert_profile",
    "match_job",
    "match_jobs",
    "score_job",
    "score_jobs",
]
