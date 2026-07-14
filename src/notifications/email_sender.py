"""AWS SES sender for the Industrial Bajío alert digest email.

Isolates the SES ``send_email`` call behind a small public surface so the rest
of the notification package stays pure and unit-testable without AWS. This
module is the ONLY place in the notifications package that talks to SES.

Design contract:

* Configuration is explicit: callers pass an :class:`EmailConfig` dataclass.
  No module-level ``os.getenv`` reads and no hidden global state -- the caller
  (the CLI in :mod:`notifications.send_digest`) owns env-var resolution.
* The boto3 client is injectable. ``client=None`` lazily builds one via
  :func:`_default_client_factory`, which imports boto3 at call time so simply
  importing this module never requires AWS credentials or network. Tests pass a
  :class:`unittest.mock.MagicMock` and never touch AWS.
* ``dry_run=True`` short-circuits before any SES call: it validates the
  region and the payload, substitutes explicit placeholders for any blank
  sender/recipient (so a local dry-run needs no verified SES identity), logs
  the intended send, and returns an :class:`EmailResult` with
  ``message_id=""``. This is the safe default for the daily digest CLI.
* Required values are validated up front with a clear, actionable
  :class:`ValueError` so a misconfigured run fails fast instead of producing a
  cryptic SES ClientError deep in boto3.

Out of scope (intentionally, for this slice): multiple recipients, CC/BCC,
unsubscribe headers, NotificationLog persistence, templating engines, retries,
and analytics. One configured recipient, one HTML body, one text fallback.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# Centralized required-field list so the validation error message and the
# validation loop stay in sync if a field is added or removed.
_REQUIRED_FIELDS: tuple[str, ...] = ("region", "from_email", "recipient_email")

# Explicit placeholders used only on the dry-run path when the operator has not
# supplied a real sender/recipient. They keep dry-runs usable locally (no
# verified SES identity needed) while making the EmailResult honest about the
# fact that no real addresses were configured. A real send never uses these --
# it validates up front and raises on blanks.
_DRY_RUN_FROM_PLACEHOLDER = "(dry-run-no-sender)"
_DRY_RUN_RECIPIENT_PLACEHOLDER = "(dry-run-no-recipient)"


class SesClient(Protocol):
    """Minimal structural type for the boto3 SES client methods we call.

    Using a Protocol keeps the sender decoupled from boto3 at type-check time
    and lets tests inject any object exposing ``send_email`` -- typically a
    :class:`unittest.mock.MagicMock`. The real boto3 ``send_email`` is called
    with keyword arguments (``Source``, ``Destination``, ``Message``); the
    Protocol only requires the method to exist, so ``**kwargs`` is sufficient.
    """

    def send_email(self, **kwargs: Any) -> dict[str, Any]:
        """SES send_email (called with Source/Destination/Message kwargs)."""
        ...


@dataclass(frozen=True)
class EmailConfig:
    """Explicit configuration for a single SES digest send.

    Attributes:
        region: AWS region for the SES client (e.g. ``"us-east-1"``).
        from_email: Verified SES sender address (the ``Source``).
        recipient_email: Single ``To`` address for the digest.
    """

    region: str
    from_email: str
    recipient_email: str


@dataclass(frozen=True)
class EmailResult:
    """Outcome of a :func:`send_email` call, safe to log or return to a CLI.

    Attributes:
        dry_run: ``True`` when no SES call was made.
        message_id: SES message id on a real send; empty string on dry run.
        recipient: The ``To`` address the send targeted.
        subject: The subject line that was sent (or would have been).
    """

    dry_run: bool
    message_id: str
    recipient: str
    subject: str


def _default_client_factory(region: str) -> SesClient:
    """Build a real boto3 SES client for ``region``.

    Imported lazily so :mod:`notifications.email_sender` can be imported in
    environments without boto3 or AWS credentials (e.g. unit tests that inject
    their own client). The import happens only on the non-dry-run path.
    """
    import boto3  # local import: keep module import side-effect free

    return boto3.client("ses", region_name=region)


def _validate_config(config: EmailConfig) -> None:
    """Fail fast on missing/blank required config before touching SES.

    Used on the real-send path. The dry-run path only enforces the region (see
    :func:`_require_region`) so a local operator can run a dry-run without a
    verified SES sender or a real recipient.

    Raises:
        ValueError: listing every blank required field in one message so the
            operator sees the full gap in a single run rather than fixing one
            field at a time.
    """
    missing = [
        name
        for name in _REQUIRED_FIELDS
        if not getattr(config, name) or not str(getattr(config, name)).strip()
    ]
    if missing:
        raise ValueError(
            "EmailConfig is missing required field(s): "
            + ", ".join(missing)
            + ". Set AWS_REGION, SES_FROM_EMAIL, and ALERT_RECIPIENT_EMAIL."
        )


def _require_region(config: EmailConfig) -> None:
    """Ensure the region is set on both dry-run and real-send paths.

    The CLI always supplies a region default (``us-east-1``), so a blank region
    only happens when :class:`EmailConfig` is constructed directly. We still
    fail fast with a clear message so a dry-run log is not produced against an
    unknown region.

    Raises:
        ValueError: if ``region`` is blank.
    """
    if not config.region or not config.region.strip():
        raise ValueError("region is required. Set AWS_REGION or pass --region.")


def _validate_payload(subject: str, html_body: str) -> None:
    """Ensure the email content is present before constructing the SES message.

    Raises:
        ValueError: if ``subject`` or ``html_body`` is blank.
    """
    if not subject or not subject.strip():
        raise ValueError("subject must be a non-empty string.")
    if not html_body or not html_body.strip():
        raise ValueError("html_body must be a non-empty string.")


def _build_ses_message(
    subject: str,
    html_body: str,
    text_body: str | None,
) -> dict[str, Any]:
    """Compose the SES ``Message`` dict with an HTML part and optional text part.

    The text fallback is only added when provided so SES does not receive an
    empty ``Text.Data`` value (which it rejects). When omitted, the email is
    HTML-only -- acceptable for this digest since the HTML is self-contained.
    """
    body: dict[str, Any] = {"Html": {"Data": html_body}}
    if text_body and text_body.strip():
        body["Text"] = {"Data": text_body}
    return {
        "Subject": {"Data": subject},
        "Body": body,
    }


def send_email(
    config: EmailConfig,
    subject: str,
    html_body: str,
    text_body: str | None = None,
    *,
    dry_run: bool = True,
    client: SesClient | None = None,
    client_factory: Any = _default_client_factory,
) -> EmailResult:
    """Send (or dry-run) a single HTML digest email via AWS SES.

    Args:
        config: Sender/recipient/region configuration. Real-send validates all
            fields up front; dry-run validates only the region and substitutes
            placeholders for blank sender/recipient.
        subject: Email subject line.
        html_body: Full HTML document body (e.g. from
            :func:`notifications.html_renderer.render_digest_html`).
        text_body: Optional plain-text fallback. Omitted from the SES payload
            when blank so SES never sees an empty text part.
        dry_run: When ``True`` (the safe default), validate the region and the
            payload but do NOT call SES; return an :class:`EmailResult` with an
            empty ``message_id``. When ``False``, call SES ``send_email``.
        client: Optional pre-built SES client. ``None`` builds one via
            ``client_factory`` on the real-send path. Inject a mock in tests.
        client_factory: Callable ``(region: str) -> SesClient`` used only when
            ``client`` is ``None`` and ``dry_run`` is ``False``. Overridable in
            tests to avoid importing boto3.

    Returns:
        An :class:`EmailResult` describing the outcome.

    Raises:
        ValueError: If any required config field (real send) or payload field
            is blank. On dry-run, only ``region`` and the payload are validated;
            blank ``from_email`` / ``recipient_email`` are replaced with explicit
            placeholders so a local dry-run never requires a verified SES
            identity.
    """
    _validate_payload(subject, html_body)

    if dry_run:
        # Dry-run must be usable locally without SES_FROM_EMAIL /
        # ALERT_RECIPIENT_EMAIL. Region is still enforced (the CLI always
        # supplies a default); from/recipient use explicit placeholders so the
        # logged intent and the EmailResult are honest about the gap.
        _require_region(config)
        from_email = config.from_email.strip() or _DRY_RUN_FROM_PLACEHOLDER
        recipient = config.recipient_email.strip() or _DRY_RUN_RECIPIENT_PLACEHOLDER
        logger.info(
            "DRY RUN: would send digest to %s from %s (subject=%r, html=%d chars).",
            recipient,
            from_email,
            subject,
            len(html_body),
        )
        return EmailResult(
            dry_run=True,
            message_id="",
            recipient=recipient,
            subject=subject,
        )

    # Real send: enforce every required field before touching SES.
    _validate_config(config)
    ses_client = client if client is not None else client_factory(config.region)
    message = _build_ses_message(subject, html_body, text_body)
    response = ses_client.send_email(
        Source=config.from_email,
        Destination={"ToAddresses": [config.recipient_email]},
        Message=message,
    )
    message_id = str(response.get("MessageId", ""))
    logger.info(
        "SES send_email accepted: message_id=%s recipient=%s subject=%r.",
        message_id,
        config.recipient_email,
        subject,
    )
    return EmailResult(
        dry_run=False,
        message_id=message_id,
        recipient=config.recipient_email,
        subject=subject,
    )
