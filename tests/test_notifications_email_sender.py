"""Tests for notifications.email_sender: AWS SES isolation layer.

Covers the ``feat/alert-email-delivery`` behavior:

* Dry-run validates config/payload but never calls SES and returns an empty
  ``message_id``.
* Real-send call shape matches SES ``send_email``: ``Source``,
  ``Destination.ToAddresses`` (single recipient), ``Message.Subject``, and an
  HTML ``Body`` part.
* Optional text fallback is added only when provided and non-blank.
* Missing required config (region / from / recipient) raises a clear
  :class:`ValueError` naming the fields.
* Blank subject or html body raises :class:`ValueError`.
* boto3 is never imported on the dry-run path and the default client factory is
  bypassed when a client is injected.

No AWS network and no boto3 import happen in this suite: the SES client is a
:class:`unittest.mock.MagicMock` and ``client_factory`` is overridden where the
real-send path is exercised.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from notifications.email_sender import (
    EmailConfig,
    EmailResult,
    send_email,
)

VALID_CONFIG = EmailConfig(
    region="us-east-1",
    from_email="alerts@example.com",
    recipient_email="brother@example.com",
)
SUBJECT = "Industrial Bajio digest: 3 new job(s)"
HTML_BODY = "<!DOCTYPE html><html><body><p>digest</p></body></html>"
TEXT_BODY = "Industrial Bajio digest: 3 new job(s)"


def _fake_ses_client() -> MagicMock:
    """SES client double that records the send_email kwargs and returns an id."""
    client = MagicMock()
    client.send_email.return_value = {"MessageId": "ses-12345"}
    return client


class TestDryRun:
    def test_dry_run_does_not_call_ses(self):
        client = _fake_ses_client()

        result = send_email(
            VALID_CONFIG, subject=SUBJECT, html_body=HTML_BODY,
            dry_run=True, client=client,
        )

        client.send_email.assert_not_called()
        assert result.dry_run is True
        assert result.message_id == ""
        assert result.recipient == "brother@example.com"
        assert result.subject == SUBJECT

    def test_dry_run_is_default_when_not_specified(self):
        client = _fake_ses_client()

        result = send_email(VALID_CONFIG, subject=SUBJECT, html_body=HTML_BODY, client=client)

        client.send_email.assert_not_called()
        assert result.dry_run is True

    def test_dry_run_returns_email_result_type(self):
        result = send_email(VALID_CONFIG, subject=SUBJECT, html_body=HTML_BODY, dry_run=True)

        assert isinstance(result, EmailResult)

    def test_dry_run_without_sender_or_recipient_uses_placeholders(self):
        """Dry-run must be usable locally without SES_FROM_EMAIL/recipient.

        A blank sender/recipient is replaced with explicit placeholders so the
        EmailResult is honest; no ValueError is raised on the dry-run path.
        """
        config = EmailConfig(region="us-east-1", from_email="", recipient_email="")

        result = send_email(config, subject=SUBJECT, html_body=HTML_BODY, dry_run=True)

        assert result.dry_run is True
        assert result.message_id == ""
        assert result.recipient == "(dry-run-no-recipient)"
        assert result.subject == SUBJECT

    def test_dry_run_preserves_real_addresses_when_provided(self):
        """When real addresses are present, dry-run uses them verbatim."""
        config = EmailConfig(
            region="us-east-1",
            from_email="alerts@example.com",
            recipient_email="brother@example.com",
        )

        result = send_email(config, subject=SUBJECT, html_body=HTML_BODY, dry_run=True)

        assert result.recipient == "brother@example.com"

    def test_dry_run_still_requires_region(self):
        """Region is enforced even on dry-run (CLI always supplies a default)."""
        config = EmailConfig(region="", from_email="", recipient_email="")

        with pytest.raises(ValueError, match="region"):
            send_email(config, subject=SUBJECT, html_body=HTML_BODY, dry_run=True)


class TestRealSend:
    def test_real_send_call_shape_includes_source_destination_subject_html(self):
        client = _fake_ses_client()

        result = send_email(
            VALID_CONFIG, subject=SUBJECT, html_body=HTML_BODY, text_body=TEXT_BODY,
            dry_run=False, client=client,
        )

        client.send_email.assert_called_once()
        kwargs = client.send_email.call_args.kwargs
        assert kwargs["Source"] == "alerts@example.com"
        assert kwargs["Destination"] == {"ToAddresses": ["brother@example.com"]}
        assert kwargs["Message"]["Subject"]["Data"] == SUBJECT
        assert kwargs["Message"]["Body"]["Html"]["Data"] == HTML_BODY
        assert kwargs["Message"]["Body"]["Text"]["Data"] == TEXT_BODY

        assert result.dry_run is False
        assert result.message_id == "ses-12345"
        assert result.recipient == "brother@example.com"
        assert result.subject == SUBJECT

    def test_real_send_without_text_body_omits_text_part(self):
        client = _fake_ses_client()

        send_email(
            VALID_CONFIG, subject=SUBJECT, html_body=HTML_BODY, text_body=None,
            dry_run=False, client=client,
        )

        body = client.send_email.call_args.kwargs["Message"]["Body"]
        assert "Html" in body
        assert "Text" not in body

    def test_real_send_with_blank_text_body_omits_text_part(self):
        client = _fake_ses_client()

        send_email(
            VALID_CONFIG, subject=SUBJECT, html_body=HTML_BODY, text_body="   ",
            dry_run=False, client=client,
        )

        body = client.send_email.call_args.kwargs["Message"]["Body"]
        assert "Text" not in body

    def test_real_send_uses_client_factory_when_client_is_none(self):
        factory_client = _fake_ses_client()
        factory = MagicMock(return_value=factory_client)

        result = send_email(
            VALID_CONFIG, subject=SUBJECT, html_body=HTML_BODY,
            dry_run=False, client=None, client_factory=factory,
        )

        factory.assert_called_once_with("us-east-1")
        factory_client.send_email.assert_called_once()
        assert result.message_id == "ses-12345"


class TestValidation:
    def test_missing_region_raises_value_error(self):
        # Region is enforced on both paths; exercise it via dry-run.
        config = EmailConfig(region="", from_email="a@x.com", recipient_email="b@x.com")

        with pytest.raises(ValueError, match="region"):
            send_email(config, subject=SUBJECT, html_body=HTML_BODY, dry_run=True)

    def test_missing_from_email_raises_on_real_send(self):
        """Real send requires a sender; dry-run tolerates a blank one."""
        config = EmailConfig(region="us-east-1", from_email="", recipient_email="b@x.com")

        with pytest.raises(ValueError, match="from_email"):
            send_email(config, subject=SUBJECT, html_body=HTML_BODY, dry_run=False)

    def test_missing_recipient_raises_on_real_send(self):
        """Real send requires a recipient; dry-run tolerates a blank one."""
        config = EmailConfig(region="us-east-1", from_email="a@x.com", recipient_email="")

        with pytest.raises(ValueError, match="recipient_email"):
            send_email(config, subject=SUBJECT, html_body=HTML_BODY, dry_run=False)

    def test_missing_all_fields_lists_all_in_one_message_on_real_send(self):
        config = EmailConfig(region="", from_email="", recipient_email="")

        with pytest.raises(ValueError) as excinfo:
            send_email(config, subject=SUBJECT, html_body=HTML_BODY, dry_run=False)

        message = str(excinfo.value)
        assert "region" in message
        assert "from_email" in message
        assert "recipient_email" in message

    def test_blank_subject_raises_value_error(self):
        with pytest.raises(ValueError, match="subject"):
            send_email(VALID_CONFIG, subject="   ", html_body=HTML_BODY, dry_run=True)

    def test_blank_html_body_raises_value_error(self):
        with pytest.raises(ValueError, match="html_body"):
            send_email(VALID_CONFIG, subject=SUBJECT, html_body="   ", dry_run=True)

    def test_validation_runs_before_ses_call(self):
        """Missing config must fail before any client interaction on real send."""
        client = _fake_ses_client()
        config = EmailConfig(region="", from_email="", recipient_email="")

        with pytest.raises(ValueError):
            send_email(config, subject=SUBJECT, html_body=HTML_BODY, dry_run=False, client=client)

        client.send_email.assert_not_called()
