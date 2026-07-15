"""Tests for the alert email Lambda entry point (lambda_functions.alert_email.handler).

Covers the ``feat/alert-email-schedule`` runtime shim:

* Dry-run remains the default when ``ALERT_EMAIL_DRY_RUN`` is unset (the safe
  invariant for a scheduled, unattended job).
* ``ALERT_EMAIL_DRY_RUN=false`` flips the delegation to a real send.
* Config (region/from/recipient) is resolved from env vars and forwarded to
  ``run_send_digest`` as an :class:`EmailConfig`.
* A successful run returns a structured 200 response with the ``EmailResult``
  summary; a failure inside the pipeline returns a 500 response and never
  re-raises (one bad invocation must not loop the schedule).

No database, no network, no SES. ``run_send_digest`` is replaced with a
``MagicMock`` so the handler exercises only resolution + response shaping.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import lambda_functions.alert_email.handler as handler_mod
from lambda_functions.alert_email.handler import lambda_handler
from notifications.email_sender import EmailConfig, EmailResult

SUCCESS_RESULT_DRY = EmailResult(
    dry_run=True,
    message_id="",
    recipient="(dry-run-no-recipient)",
    subject="Industrial Bajio digest: 1 new job(s)",
)
SUCCESS_RESULT_SEND = EmailResult(
    dry_run=False,
    message_id="ses-abc-123",
    recipient="brother@example.com",
    subject="Industrial Bajio digest: 1 new job(s)",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Isolate every run from host environment to keep tests deterministic.

    The conventional guard for env-var-free tests: clear all five env vars the
    handler cares about so each case sets only what it exercises.
    """
    for name in (
        "DATABASE_URL",
        "AWS_REGION",
        "SES_FROM_EMAIL",
        "ALERT_RECIPIENT_EMAIL",
        "ALERT_EMAIL_DRY_RUN",
    ):
        monkeypatch.delenv(name, raising=False)


def fake_run_digest(return_value: EmailResult) -> MagicMock:
    """Mock replacing ``run_send_digest`` and recording the call."""
    fn = MagicMock(return_value=return_value)
    return fn


class TestLambdaHandlerDefaultDryRun:
    def test_unsupported_dry_run_env_defaults_to_dry_run(self, monkeypatch):
        """When ALERT_EMAIL_DRY_RUN is unset the Lambda must delegate with dry_run=True."""
        monkeypatch.delenv("ALERT_EMAIL_DRY_RUN", raising=False)
        run = fake_run_digest(SUCCESS_RESULT_DRY)
        monkeypatch.setattr(handler_mod, "run_send_digest", run)

        response = lambda_handler({}, None)

        assert response["statusCode"] == 200
        run.assert_called_once()
        assert run.call_args.kwargs["dry_run"] is True

    def test_dry_run_env_true_keeps_dry_run(self, monkeypatch):
        monkeypatch.setenv("ALERT_EMAIL_DRY_RUN", "true")
        run = fake_run_digest(SUCCESS_RESULT_DRY)
        monkeypatch.setattr(handler_mod, "run_send_digest", run)

        response = lambda_handler({}, None)

        assert response["statusCode"] == 200
        assert run.call_args.kwargs["dry_run"] is True
        assert response["result"]["dry_run"] is True
        assert response["result"]["message_id"] == ""


class TestLambdaHandlerRealSend:
    def test_env_false_delegates_with_dry_run_false(self, monkeypatch):
        monkeypatch.setenv("ALERT_EMAIL_DRY_RUN", "false")
        monkeypatch.setenv("SES_FROM_EMAIL", "alerts@example.com")
        monkeypatch.setenv("ALERT_RECIPIENT_EMAIL", "brother@example.com")
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        run = fake_run_digest(SUCCESS_RESULT_SEND)
        monkeypatch.setattr(handler_mod, "run_send_digest", run)

        response = lambda_handler({}, None)

        assert response["statusCode"] == 200
        assert run.call_args.kwargs["dry_run"] is False
        forwarded_config = run.call_args.args[0]
        assert isinstance(forwarded_config, EmailConfig)
        assert forwarded_config.region == "us-east-1"
        assert forwarded_config.from_email == "alerts@example.com"
        assert forwarded_config.recipient_email == "brother@example.com"
        assert response["result"]["message_id"] == "ses-abc-123"
        assert response["result"]["dry_run"] is False

    def test_region_defaults_to_us_east_1_when_unset(self, monkeypatch):
        monkeypatch.delenv("AWS_REGION", raising=False)
        monkeypatch.setenv("ALERT_EMAIL_DRY_RUN", "false")
        run = fake_run_digest(SUCCESS_RESULT_SEND)
        monkeypatch.setattr(handler_mod, "run_send_digest", run)

        response = lambda_handler({}, None)

        assert response["statusCode"] == 200
        assert run.call_args.args[0].region == "us-east-1"


class TestLambdaHandlerErrorPath:
    def test_invalid_dry_run_env_returns_500_without_reraising(self, monkeypatch):
        """A typo such as ``ALERT_EMAIL_DRY_RUN=maybe`` must surface as a 500, not raise.

        Regression guard for the fail-closed ``resolve_dry_run`` behavior: the
        handler must convert the ValueError into a structured error response so
        EventBridge Scheduler is not told the invocation threw.
        """
        monkeypatch.setenv("ALERT_EMAIL_DRY_RUN", "maybe")
        run = fake_run_digest(SUCCESS_RESULT_SEND)
        monkeypatch.setattr(handler_mod, "run_send_digest", run)

        response = lambda_handler({}, None)

        assert response["statusCode"] == 500
        run.assert_not_called()
        assert "Alert email run failed" in response["body"]

    def test_run_send_digest_failure_returns_500(self, monkeypatch):
        monkeypatch.setenv("ALERT_EMAIL_DRY_RUN", "true")
        run = MagicMock()
        run.side_effect = RuntimeError("database unreachable")
        monkeypatch.setattr(handler_mod, "run_send_digest", run)

        response = lambda_handler({}, None)

        assert response["statusCode"] == 500
        assert "database unreachable" in response["body"]
        assert "result" not in response

    def test_real_send_blank_recipient_returns_500(self, monkeypatch):
        """A real send with no recipient surfaces the sender's ValueError as 500."""
        monkeypatch.setenv("ALERT_EMAIL_DRY_RUN", "false")
        run = MagicMock()
        run.side_effect = ValueError("EmailConfig is missing required field(s): recipient_email")
        monkeypatch.setattr(handler_mod, "run_send_digest", run)

        response = lambda_handler({}, None)

        assert response["statusCode"] == 500
        assert "recipient_email" in response["body"]


class TestLambdaHandlerResponseShape:
    def test_success_response_body_summarizes_dry_run(self, monkeypatch):
        monkeypatch.setenv("ALERT_EMAIL_DRY_RUN", "true")
        run = fake_run_digest(SUCCESS_RESULT_DRY)
        monkeypatch.setattr(handler_mod, "run_send_digest", run)

        response = lambda_handler({}, None)

        assert response["statusCode"] == 200
        assert "no SES call" in response["body"]
        assert response["result"] == {
            "dry_run": True,
            "message_id": "",
            "recipient": "(dry-run-no-recipient)",
            "subject": "Industrial Bajio digest: 1 new job(s)",
        }

    def test_success_response_body_summarizes_real_send(self, monkeypatch):
        monkeypatch.setenv("ALERT_EMAIL_DRY_RUN", "false")
        monkeypatch.setenv("SES_FROM_EMAIL", "alerts@example.com")
        monkeypatch.setenv("ALERT_RECIPIENT_EMAIL", "brother@example.com")
        run = fake_run_digest(SUCCESS_RESULT_SEND)
        monkeypatch.setattr(handler_mod, "run_send_digest", run)

        response = lambda_handler({}, None)

        assert response["statusCode"] == 200
        assert "message_id=ses-abc-123" in response["body"]
        assert response["result"]["dry_run"] is False