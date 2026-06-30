"""Notifications package: alert profiles and deterministic job matching.

This package is the foundation for the alert system. It currently provides
subscriber alert profiles (:mod:`notifications.profiles`) and a pure, deterministic
job matcher (:mod:`notifications.matcher`). Email sending, notification logging,
and database persistence are intentionally out of scope for this foundation slice.
"""
from __future__ import annotations

from notifications.matcher import match_job, match_jobs
from notifications.profiles import (
    ALERT_PROFILES,
    INDUSTRIAL_IRAPUATO_BAJIO_PROFILE,
    AlertProfile,
    get_alert_profile,
)

__all__ = [
    "AlertProfile",
    "ALERT_PROFILES",
    "INDUSTRIAL_IRAPUATO_BAJIO_PROFILE",
    "get_alert_profile",
    "match_job",
    "match_jobs",
]
