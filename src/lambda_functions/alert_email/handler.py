"""AWS Lambda entry point for the daily Industrial Bajío alert digest email.

This is a thin runtime shim only: it resolves the sender config and the dry-run
flag from environment variables (reusing the existing ``notifications.send_digest``
resolution helpers) and delegates build + render + send to
:func:`notifications.send_digest.run_send_digest`. No digest logic, no SES
calls, and no database code live here -- the heavy lifting stays in the
notifications package so the runtime contract and its tests stay unchanged.

Architecture contract for this scheduled job:

* Read-only over the existing job DB: it builds the digest from already-scraped
  rows and sends (or dry-runs) through SES. It must NEVER hit job boards /
  scrapers. That property is inherited from ``run_send_digest`` -> ``build_digest``
  -> :func:`notifications.digest_repository.build_digest`, which only queries
  the Supabase ``jobs`` table.

* Scheduled by Terraform via EventBridge Scheduler at 8:00 AM ``America/Mexico_City``.
  The scheduler assumes a role and invokes this Lambda; it does NOT use an S3
  trigger, so no ``aws_lambda_permission`` for a service principal is needed
  here.

* Safe by default: dry-run unless ``ALERT_EMAIL_DRY_RUN=false``. The schedule
  ships disabled-safe: a fresh deploy with ``ALERT_EMAIL_DRY_RUN`` unset will
  build and log the digest but will NOT call SES.

Env vars (owned by the existing send_digest resolver, not re-read here):
    DATABASE_URL:           Supabase Postgres URL. Required; read by db_connect.
    AWS_REGION:             SES client region. Defaults to ``us-east-1``.
    SES_FROM_EMAIL:         Verified SES sender (Source). Required for a real send.
    ALERT_RECIPIENT_EMAIL:  Single To address. Required for a real send.
    ALERT_EMAIL_DRY_RUN:    ``"true"``/``"false"``; defaults to ``"true"`` (safe).

Response shape (EventBridge Scheduler ignores the return, but we keep it
structured for manual invocations and tests)::

    {
        "statusCode": 200 | 500,
        "body": <summary string>,
        "result": {          # present on success
            "dry_run": bool,
            "message_id": str,
            "recipient": str,
            "subject": str
        }
    }

Runtime deps NOT bundled by the Terraform zip: ``sqlalchemy``,
``psycopg2-binary``, and ``python-dotenv``. Provide them via a Lambda Layer
(see the module docs). ``boto3`` is provided by the Lambda runtime itself.
"""
from __future__ import annotations

import logging
from typing import Any

from notifications.email_sender import EmailConfig, EmailResult
from notifications.send_digest import resolve_config, resolve_dry_run, run_send_digest

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_DRY_RUN_RESOLVED_MESSAGE = (
    "Alert email invocation resolved dry_run=%s; delegating to run_send_digest."
)


def _resolve_and_run(run_send_digest_fn: Any) -> EmailResult:
    """Resolve config/dry-run from env and delegate one digest run.

    Reuses ``resolve_config`` and ``resolve_dry_run`` so the resolution rules
    (CLI flags unused here -> both False -> env var decides, defaulting to dry
    run) stay identical to the CLI path. The injected ``run_send_digest_fn``
    makes the entry point unit-testable without a database, SES, or network.

    Args:
        run_send_digest_fn: Callable with the same signature as
            :func:`notifications.send_digest.run_send_digest`. Injected so
            tests can pass a mock and avoid the real DB/SES path.

    Returns:
        The :class:`EmailResult` from the delegated run.

    Raises:
        ValueError: If ``ALERT_EMAIL_DRY_RUN`` holds an unrecognized value
            (propagated from :func:`resolve_dry_run`, which fails closed).
        ValueError: If a real send is requested and any required config field
            is blank (propagated from ``send_email``).
    """
    config: EmailConfig = resolve_config(region=None, from_email=None, recipient_email=None)
    dry_run = resolve_dry_run(send_flag=False, dry_run_flag=False)
    logger.info(_DRY_RUN_RESOLVED_MESSAGE, dry_run)
    return run_send_digest_fn(config, dry_run=dry_run)


def _success_response(result: EmailResult) -> dict[str, Any]:
    """Build the Lambda success return for a digest run outcome."""
    summary = (
        "Dry-run complete: no SES call made." if result.dry_run
        else f"Digest sent: message_id={result.message_id} recipient={result.recipient}"
    )
    logger.info(summary)
    return {
        "statusCode": 200,
        "body": summary,
        "result": {
            "dry_run": result.dry_run,
            "message_id": result.message_id,
            "recipient": result.recipient,
            "subject": result.subject,
        },
    }


def _error_response(error: BaseException) -> dict[str, Any]:
    """Build the Lambda failure return, logging the full traceback.

    EventBridge Scheduler does not retry on a function return value, but a 500
    here surfaces in CloudWatch Logs for diagnosis. We do not re-raise so one
    invocation failure does not loop the schedule.
    """
    logger.exception("Alert email Lambda failed: %s", error)
    return {
        "statusCode": 500,
        "body": f"Alert email run failed: {error}",
    }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """EventBridge Scheduler entry point: build, render, and send/dry-run the daily digest.

    Ignores ``event`` and ``context`` -- the scheduled job takes no custom
    payload and has no custom callback. The digest is always built from the
    current DB state at invocation time.
    """
    try:
        result = _resolve_and_run(run_send_digest)
    except Exception as error:
        # Convention permits a broad catch when we log the full traceback and
        # do not swallow it silently; logger.exception captures the stack.
        return _error_response(error)
    return _success_response(result)