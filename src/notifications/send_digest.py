"""CLI entry point to build and send the daily Industrial Bajío digest email.

Reuses the existing digest builder (:func:`notifications.digest_repository.
build_digest`) and HTML renderer (:func:`notifications.html_renderer.
render_digest_html`), then delegates the actual send to :mod:`notifications.
email_sender`. This module is orchestration only -- no new digest logic, no new
rendering, and no SES calls live here.

Safe by default: dry-run unless the operator explicitly opts into a real send
via ``--send`` OR ``ALERT_EMAIL_DRY_RUN=false``. In dry-run, the digest is
still built from the real database and rendered (so the operator can see the
actual HTML that would go out), but no SES call is made and the required
``SES_FROM_EMAIL`` / ``ALERT_RECIPIENT_EMAIL`` env vars are NOT enforced.

Run locally::

    # Dry run (default): builds, renders, logs -- never calls SES.
    PYTHONPATH=src python -m notifications.send_digest

    # Real send: requires SES_FROM_EMAIL and ALERT_RECIPIENT_EMAIL.
    PYTHONPATH=src python -m notifications.send_digest --send

    # Override recipient / from / region from the CLI without env vars.
    PYTHONPATH=src python -m notifications.send_digest --send \\
        --from-email alerts@example.com --recipient brother@example.com

Env vars:
    AWS_REGION: SES client region. Defaults to ``us-east-1``.
    SES_FROM_EMAIL: Verified SES sender address. Required for a real send.
    ALERT_RECIPIENT_EMAIL: Single To address. Required for a real send.
    ALERT_EMAIL_DRY_RUN: ``"true"``/``"false"``. Defaults to ``"true"``. The
        ``--send`` flag overrides this to ``false``; ``--dry-run`` to ``true``.
        An invalid value (e.g. a typo like ``"flase"``) raises :class:`ValueError`
        rather than silently defaulting to a real send.
"""
from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from database.models import db_connect
from notifications.digest import DigestPayload
from notifications.digest_repository import build_digest
from notifications.email_sender import EmailConfig, EmailResult, send_email
from notifications.html_renderer import render_digest_html

logger = logging.getLogger(__name__)

DEFAULT_AWS_REGION = "us-east-1"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _open_session() -> Session:
    """Create a SQLAlchemy session bound to the configured Supabase engine.

    Mirrors :mod:`notifications.preview`: lazy engine via
    :func:`database.models.db_connect` so module import never opens a
    connection. The caller closes the session.
    """
    engine = db_connect()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


def _default_build_digest(now: datetime) -> DigestPayload:
    """Build the real Industrial Bajío digest from Supabase and close the session."""
    session = _open_session()
    try:
        return build_digest(session, now)
    finally:
        session.close()


def digest_subject(payload: DigestPayload) -> str:
    """Build the email subject line for a digest payload.

    Matches the headline the renderer places in the ``<title>`` so the inbox
    preview and the opened email agree on the count. ``total`` is primary +
    fallback, identical to :func:`notifications.html_renderer.render_digest_html`.
    """
    total = payload.count + len(payload.fallback_jobs)
    return f"Industrial Bajio digest: {total} new job(s)"


def _bool_env(name: str, default: bool) -> bool:
    """Read a boolean env var, failing closed on unrecognized values.

    Unset or blank returns ``default``. Recognized truthy/falsy values return
    ``True``/``False``. Any other value raises :class:`ValueError` so a typo
    such as ``"flase"`` can never silently flip a safety flag -- for
    ``ALERT_EMAIL_DRY_RUN`` that would mean an unintended real SES send, which
    is exactly the unsafe outcome we refuse to tolerate silently.

    Args:
        name: Environment variable name (used in the error message).
        default: Value returned when the env var is unset or blank.

    Returns:
        The parsed boolean.

    Raises:
        ValueError: If the env var is set to a value that is neither a
            recognized truthy nor falsy token.
    """
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise ValueError(
        f"Invalid boolean for env var {name!r}: {raw!r}. "
        f"Accepted (case-insensitive) truthy: {sorted(_TRUE_VALUES)}; "
        f"falsy: {sorted(_FALSE_VALUES)}."
    )


def resolve_config(
    *,
    region: str | None,
    from_email: str | None,
    recipient_email: str | None,
) -> EmailConfig:
    """Build an :class:`EmailConfig` from CLI flags with env-var fallbacks.

    CLI flags take precedence over env vars; env vars fill the gaps. Region
    falls back to :data:`DEFAULT_AWS_REGION` when neither is set, so a real send
    in the default AWS region does not require the operator to set ``AWS_REGION``.
    """
    return EmailConfig(
        region=(region or os.getenv("AWS_REGION") or DEFAULT_AWS_REGION),
        from_email=from_email or os.getenv("SES_FROM_EMAIL", ""),
        recipient_email=recipient_email or os.getenv("ALERT_RECIPIENT_EMAIL", ""),
    )


def resolve_dry_run(*, send_flag: bool, dry_run_flag: bool) -> bool:
    """Decide dry-run vs real send from explicit CLI flags and the env default.

    ``--send`` and ``--dry-run`` are mutually exclusive and override the
    ``ALERT_EMAIL_DRY_RUN`` env var. When neither flag is set, the env var
    decides (defaulting to dry-run / safe).
    """
    if send_flag:
        return False
    if dry_run_flag:
        return True
    # ALERT_EMAIL_DRY_RUN defaults to true (safe): env "true" -> dry run on.
    return _bool_env("ALERT_EMAIL_DRY_RUN", default=True)


def run_send_digest(
    config: EmailConfig,
    *,
    dry_run: bool,
    now: datetime | None = None,
    build_digest_fn: Callable[[datetime], DigestPayload] | None = None,
    render_fn: Callable[[DigestPayload], str] | None = None,
) -> EmailResult:
    """Build, render, and send (or dry-run) the daily Industrial Bajío digest.

    Orchestrates three steps:

    1. Build a :class:`DigestPayload` (real Supabase data by default, or an
       injected callable for tests).
    2. Render the payload to HTML via the pure renderer.
    3. Send via :func:`notifications.email_sender.send_email` with the
       resolved dry-run flag.

    Args:
        config: Sender/recipient/region configuration. On a real send,
            :func:`send_email` validates required fields and raises
            :class:`ValueError` if any are blank. On dry-run, blank
            ``from_email`` / ``recipient_email`` are tolerated.
        dry_run: When ``True``, no SES call is made.
        now: Reference datetime for the digest freshness window. ``None``
            resolves to ``datetime.now(timezone.utc)``.
        build_digest_fn: Callable ``(now: datetime) -> DigestPayload``. ``None``
            uses :func:`_default_build_digest`, which opens a real Supabase
            session. Inject a fake in tests to avoid the DB.
        render_fn: Callable ``(DigestPayload) -> str``. ``None`` uses
            :func:`notifications.html_renderer.render_digest_html`.

    Returns:
        The :class:`EmailResult` from :func:`send_email`.
    """
    resolved_now = now if now is not None else datetime.now(UTC)
    build = build_digest_fn if build_digest_fn is not None else _default_build_digest
    render = render_fn if render_fn is not None else render_digest_html

    payload = build(resolved_now)
    html = render(payload)
    subject = digest_subject(payload)

    logger.info(
        "Digest built: %d primary job(s), %d fallback job(s). Sending (dry_run=%s).",
        payload.count,
        len(payload.fallback_jobs),
        dry_run,
    )
    return send_email(config, subject=subject, html_body=html, dry_run=dry_run)


def _cli() -> None:
    """Parse args, resolve config/dry-run, and run one digest send."""
    parser = argparse.ArgumentParser(
        description=(
            "Build and send the daily Industrial Bajío digest email. "
            "Safe by default: dry-run unless --send is given or "
            "ALERT_EMAIL_DRY_RUN=false."
        ),
    )
    send_group = parser.add_mutually_exclusive_group()
    send_group.add_argument(
        "--send",
        action="store_true",
        help="Actually call SES (requires SES_FROM_EMAIL and ALERT_RECIPIENT_EMAIL).",
    )
    send_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and log only; never call SES (default behavior).",
    )
    parser.add_argument(
        "--recipient",
        default=None,
        help="Override ALERT_RECIPIENT_EMAIL for this run.",
    )
    parser.add_argument(
        "--from-email",
        default=None,
        help="Override SES_FROM_EMAIL for this run.",
    )
    parser.add_argument(
        "--region",
        default=None,
        help=f"Override AWS_REGION for this run (default: {DEFAULT_AWS_REGION}).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    config = resolve_config(
        region=args.region,
        from_email=args.from_email,
        recipient_email=args.recipient,
    )
    dry_run = resolve_dry_run(send_flag=args.send, dry_run_flag=args.dry_run)

    result = run_send_digest(config, dry_run=dry_run)
    if result.dry_run:
        logger.info(
            "Dry-run complete. No email sent. Use --send to deliver to %s.",
            config.recipient_email or "(unset ALERT_RECIPIENT_EMAIL)",
        )
    else:
        logger.info(
            "Send complete: message_id=%s recipient=%s.",
            result.message_id,
            result.recipient,
        )


if __name__ == "__main__":
    _cli()
