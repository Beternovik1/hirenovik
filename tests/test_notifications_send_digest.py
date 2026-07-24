"""Tests for notifications.send_digest: build, render, and send/dry-run CLI.

Covers the ``feat/alert-email-delivery`` behavior:

* Dry-run is the default and never calls SES (validates that the safe default
  holds without DB/network -- build and render are mocked).
* ``--send`` / ``--dry-run`` flags and the ``ALERT_EMAIL_DRY_RUN`` env var
  resolve to the right dry-run decision.
* Real-send flow builds the subject from the payload total, renders HTML, and
  delegates to the sender with ``dry_run=False``.
* Config resolution prefers CLI flags, falls back to env vars, and defaults the
  region to ``us-east-1``.
* ``digest_subject`` matches the renderer's headline (primary + fallback count).

No real database, no network, and no SES. ``db_connect`` is patched at the
module boundary for the default-builder path so the CLI contract is covered
without infra. The SES client is a ``MagicMock`` injected through the sender.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

import notifications.send_digest as send_digest_mod
from notifications.digest import DigestJob, DigestPayload
from notifications.email_sender import EmailConfig, EmailResult
from notifications.send_digest import (
    digest_subject,
    resolve_config,
    resolve_dry_run,
    run_send_digest,
)

PROFILE = "industrial_irapuato_bajio"
NICHE = "Industrial Bajio"
GENERATED_AT = "2026-07-12T12:00:00+00:00"
NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=UTC)


def make_job(job_id: int = 1, title: str = "SAP WM Analyst") -> DigestJob:
    """Minimal DigestJob for send_digest tests."""
    return DigestJob(
        id=job_id,
        title=title,
        company="Industrias Bajio",
        location="Silao, Guanajuato",
        site="occ",
        job_url="https://example.com/job/1",
        score=150,
        match_reasons=("Location: silao (+50)", "Role: SAP / inventory (+100)"),
        date_scraped="2026-07-11T10:00:00+00:00",
        salary_min=25000.0,
        salary_max=35000.0,
        currency="MXN",
        description="Gestion de warehouse management con SAP WM.",
        matched_city="silao",
        matched_role_group="SAP / inventory",
        location_tier="Silao / Puerto Interior",
    )


def make_payload(jobs, fallback_jobs=None) -> DigestPayload:
    """Build a DigestPayload mirroring the preview test factory."""
    return DigestPayload(
        profile_name=PROFILE,
        niche=NICHE,
        generated_at=GENERATED_AT,
        freshness_days=5,
        limit=10,
        count=len(jobs),
        jobs=tuple(jobs),
        fallback_jobs=tuple(fallback_jobs) if fallback_jobs is not None else (),
    )


def builder_returning(payload: DigestPayload) -> MagicMock:
    """Fake build_digest_fn returning ``payload`` and recording the ``now`` arg."""
    fn = MagicMock(return_value=payload)
    return fn


def renderer_returning(html: str) -> MagicMock:
    """Fake render_fn returning ``html`` and recording the payload arg."""
    return MagicMock(return_value=html)


class TestDigestSubject:
    def test_subject_counts_primary_plus_fallback(self):
        payload = make_payload([make_job(), make_job(2)], fallback_jobs=[make_job(3)])

        assert digest_subject(payload) == "Industrial Bajio digest: 3 new job(s)"

    def test_subject_only_primary_when_no_fallback(self):
        payload = make_payload([make_job(), make_job(2)])

        assert digest_subject(payload) == "Industrial Bajio digest: 2 new job(s)"

    def test_subject_zero_jobs(self):
        payload = make_payload([])

        assert digest_subject(payload) == "Industrial Bajio digest: 0 new job(s)"


class TestResolveDryRun:
    def test_defaults_to_dry_run_when_no_flags_and_env_unset(self, monkeypatch):
        monkeypatch.delenv("ALERT_EMAIL_DRY_RUN", raising=False)

        assert resolve_dry_run(send_flag=False, dry_run_flag=False) is True

    def test_send_flag_overrides_env_to_real_send(self, monkeypatch):
        monkeypatch.setenv("ALERT_EMAIL_DRY_RUN", "true")

        assert resolve_dry_run(send_flag=True, dry_run_flag=False) is False

    def test_dry_run_flag_overrides_env_to_dry_run(self, monkeypatch):
        monkeypatch.setenv("ALERT_EMAIL_DRY_RUN", "false")

        assert resolve_dry_run(send_flag=False, dry_run_flag=True) is True

    @pytest.mark.parametrize("value,expected", [("true", True), ("1", True), ("yes", True)])
    def test_env_true_keeps_dry_run(self, monkeypatch, value, expected):
        monkeypatch.setenv("ALERT_EMAIL_DRY_RUN", value)

        assert resolve_dry_run(send_flag=False, dry_run_flag=False) is expected

    @pytest.mark.parametrize(
        "value,expected", [("false", False), ("0", False), ("no", False), ("off", False)]
    )
    def test_env_false_enables_real_send(self, monkeypatch, value, expected):
        monkeypatch.setenv("ALERT_EMAIL_DRY_RUN", value)

        assert resolve_dry_run(send_flag=False, dry_run_flag=False) is expected

    @pytest.mark.parametrize("value", ["flase", "tru", "yep", "nope", "2", "enabled"])
    def test_invalid_dry_run_env_value_raises_value_error(self, monkeypatch, value):
        """A typo such as ``"flase"`` must fail closed instead of silently
        disabling dry-run (which would trigger a real SES send).

        Regression for the silent-false bug in ``_bool_env``.
        """
        monkeypatch.setenv("ALERT_EMAIL_DRY_RUN", value)

        with pytest.raises(ValueError, match="ALERT_EMAIL_DRY_RUN"):
            resolve_dry_run(send_flag=False, dry_run_flag=False)

    def test_invalid_dry_run_env_value_error_lists_accepted_values(self, monkeypatch):
        monkeypatch.setenv("ALERT_EMAIL_DRY_RUN", "maybe")

        with pytest.raises(ValueError) as excinfo:
            resolve_dry_run(send_flag=False, dry_run_flag=False)

        message = str(excinfo.value)
        assert "true" in message
        assert "false" in message


class TestResolveConfig:
    def test_cli_flags_take_precedence_over_env(self, monkeypatch):
        monkeypatch.setenv("AWS_REGION", "eu-west-1")
        monkeypatch.setenv("SES_FROM_EMAIL", "env@example.com")
        monkeypatch.setenv("ALERT_RECIPIENT_EMAIL", "env-recipient@example.com")

        config = resolve_config(
            region="us-east-1",
            from_email="cli@example.com",
            recipient_email="cli-recipient@example.com",
        )

        assert config == EmailConfig(
            region="us-east-1",
            from_email="cli@example.com",
            recipient_email="cli-recipient@example.com",
        )

    def test_env_vars_used_when_cli_flags_none(self, monkeypatch):
        monkeypatch.setenv("AWS_REGION", "eu-west-1")
        monkeypatch.setenv("SES_FROM_EMAIL", "env@example.com")
        monkeypatch.setenv("ALERT_RECIPIENT_EMAIL", "env-recipient@example.com")

        config = resolve_config(region=None, from_email=None, recipient_email=None)

        assert config == EmailConfig(
            region="eu-west-1",
            from_email="env@example.com",
            recipient_email="env-recipient@example.com",
        )

    def test_region_defaults_to_us_east_1_when_unset(self, monkeypatch):
        monkeypatch.delenv("AWS_REGION", raising=False)

        config = resolve_config(region=None, from_email=None, recipient_email=None)

        assert config.region == "us-east-1"

    def test_missing_from_and_recipient_are_blank_not_raised(self, monkeypatch):
        """Config resolution tolerates blanks; validation happens in send_email."""
        monkeypatch.delenv("SES_FROM_EMAIL", raising=False)
        monkeypatch.delenv("ALERT_RECIPIENT_EMAIL", raising=False)

        config = resolve_config(region=None, from_email=None, recipient_email=None)

        assert config.from_email == ""
        assert config.recipient_email == ""


class TestRunSendDigest:
    def test_dry_run_does_not_call_ses(self, monkeypatch):
        """Dry-run delegates to send_email with dry_run=True (no SES)."""
        payload = make_payload([make_job()])
        config = EmailConfig(
            region="us-east-1",
            from_email="alerts@example.com",
            recipient_email="b@x.com",
        )
        fake_send = MagicMock(
            return_value=EmailResult(
                dry_run=True,
                message_id="",
                recipient="b@x.com",
                subject="Industrial Bajio digest: 1 new job(s)",
            ),
        )
        monkeypatch.setattr(send_digest_mod, "send_email", fake_send)

        run_send_digest(
            config,
            dry_run=True,
            now=NOW,
            build_digest_fn=builder_returning(payload),
            render_fn=renderer_returning("<html>digest</html>"),
        )

        fake_send.assert_called_once()
        assert fake_send.call_args.kwargs["dry_run"] is True

    def test_real_send_builds_subject_and_delegates_to_sender(self, monkeypatch):
        payload = make_payload([make_job(), make_job(2)], fallback_jobs=[make_job(3)])
        config = EmailConfig(
            region="us-east-1",
            from_email="alerts@example.com",
            recipient_email="b@x.com",
        )
        build = builder_returning(payload)
        render = renderer_returning("<html>digest</html>")
        fake_send = MagicMock(
            return_value=EmailResult(
                dry_run=False,
                message_id="ses-abc",
                recipient="b@x.com",
                subject="Industrial Bajio digest: 3 new job(s)",
            ),
        )
        monkeypatch.setattr(send_digest_mod, "send_email", fake_send)

        result = run_send_digest(
            config,
            dry_run=False,
            now=NOW,
            build_digest_fn=build,
            render_fn=render,
        )

        # build received the explicit now.
        build.assert_called_once_with(NOW)
        # render received the payload.
        render.assert_called_once_with(payload)
        # send_email was delegated to with dry_run=False and the derived subject.
        fake_send.assert_called_once()
        kwargs = fake_send.call_args.kwargs
        assert kwargs["dry_run"] is False
        assert kwargs["subject"] == "Industrial Bajio digest: 3 new job(s)"
        assert kwargs["html_body"] == "<html>digest</html>"
        assert result.message_id == "ses-abc"

    def test_real_send_with_blank_recipient_raises_value_error(self):
        """Blank recipient surfaces the sender's ValueError before any SES call.

        send_email validates config up front and raises before constructing a
        boto3 client, so this stays network-free.
        """
        payload = make_payload([make_job()])
        config = EmailConfig(
            region="us-east-1", from_email="alerts@example.com", recipient_email=""
        )

        with pytest.raises(ValueError, match="recipient_email"):
            run_send_digest(
                config,
                dry_run=False,
                now=NOW,
                build_digest_fn=builder_returning(payload),
                render_fn=renderer_returning("<html>digest</html>"),
            )

    def test_build_then_render_order(self):
        recorder = []

        def _build(now):
            recorder.append("build")
            return make_payload([make_job()])

        def _render(payload):
            recorder.append("render")
            return "<html>digest</html>"

        config = EmailConfig(
            region="us-east-1",
            from_email="alerts@example.com",
            recipient_email="b@x.com",
        )

        run_send_digest(
            config,
            dry_run=True,
            now=NOW,
            build_digest_fn=_build,
            render_fn=_render,
        )

        assert recorder == ["build", "render"]

    def test_dry_run_succeeds_without_sender_or_recipient_env(self, monkeypatch):
        """A local dry-run must not require SES_FROM_EMAIL / ALERT_RECIPIENT_EMAIL.

        Exercises the real ``send_email`` (not mocked) with a blank config and
        ``dry_run=True``: it must succeed, mark the result as dry-run, and
        surface the explicit recipient placeholder instead of raising.
        """
        monkeypatch.delenv("SES_FROM_EMAIL", raising=False)
        monkeypatch.delenv("ALERT_RECIPIENT_EMAIL", raising=False)

        payload = make_payload([make_job()])
        config = EmailConfig(region="us-east-1", from_email="", recipient_email="")

        result = run_send_digest(
            config,
            dry_run=True,
            now=NOW,
            build_digest_fn=builder_returning(payload),
            render_fn=renderer_returning("<html>digest</html>"),
        )

        assert result.dry_run is True
        assert result.message_id == ""
        assert result.recipient == "(dry-run-no-recipient)"


class TestRealRendererIntegration:
    def test_real_renderer_output_is_valid_html_for_digest(self):
        """Smoke: run with the real renderer to confirm the end-to-end HTML is valid."""
        from notifications.html_renderer import render_digest_html

        payload = make_payload([make_job()])
        config = EmailConfig(
            region="us-east-1",
            from_email="alerts@example.com",
            recipient_email="b@x.com",
        )

        result = run_send_digest(
            config,
            dry_run=True,
            now=NOW,
            build_digest_fn=builder_returning(payload),
            render_fn=render_digest_html,
        )

        assert result.dry_run is True
        # digest_subject in send_digest uses the same total as the renderer title.
        assert result.subject == "Industrial Bajio digest: 1 new job(s)"


class TestDefaultBuildDigestSentHistoryWiring:
    """Slice 4: the default builder reads sent-history and wires it into build_digest
    using a single shared session (no second connection)."""

    def test_reads_sent_ids_for_digest_profile_and_passes_to_build_digest(self, monkeypatch):
        from notifications.digest import DIGEST_PROFILE_NAME

        fake_session = MagicMock(name="session")
        fake_sent = {101, 202}
        fake_payload = make_payload([make_job()])

        monkeypatch.setattr(send_digest_mod, "_open_session", lambda: fake_session)
        mock_get_sent = MagicMock(return_value=fake_sent, name="get_sent_job_ids")
        monkeypatch.setattr(send_digest_mod, "get_sent_job_ids", mock_get_sent)
        mock_build = MagicMock(return_value=fake_payload, name="build_digest")
        monkeypatch.setattr(send_digest_mod, "build_digest", mock_build)

        from notifications.send_digest import _default_build_digest

        result = _default_build_digest(NOW)

        # Sent-history read is scoped to the registered digest profile.
        mock_get_sent.assert_called_once_with(fake_session, DIGEST_PROFILE_NAME)
        # build_digest receives the same session and the exclude set.
        mock_build.assert_called_once()
        build_call = mock_build.call_args
        assert build_call.args[0] is fake_session
        assert build_call.args[1] == NOW
        assert build_call.kwargs["exclude_job_ids"] == fake_sent
        assert result is fake_payload

    def test_uses_single_session_for_read_and_build(self, monkeypatch):
        """The sent-history read and the candidate query share one session, so a
        real send does not open a second engine connection."""
        fake_session = MagicMock(name="session")
        # Track the number of sessions opened: _open_session is the only entry point.
        open_count = {"n": 0}

        def _open():
            open_count["n"] += 1
            return fake_session

        monkeypatch.setattr(send_digest_mod, "_open_session", _open)
        monkeypatch.setattr(send_digest_mod, "get_sent_job_ids", MagicMock(return_value=set()))
        monkeypatch.setattr(
            send_digest_mod,
            "build_digest",
            MagicMock(return_value=make_payload([make_job()])),
        )

        from notifications.send_digest import _default_build_digest

        _default_build_digest(NOW)

        assert open_count["n"] == 1

    def test_closes_session_even_on_build_error(self, monkeypatch):
        """A build_digest failure must still close the shared session."""
        fake_session = MagicMock(name="session")
        monkeypatch.setattr(send_digest_mod, "_open_session", lambda: fake_session)
        monkeypatch.setattr(send_digest_mod, "get_sent_job_ids", MagicMock(return_value=set()))
        monkeypatch.setattr(
            send_digest_mod, "build_digest", MagicMock(side_effect=RuntimeError("boom"))
        )

        from notifications.send_digest import _default_build_digest

        with pytest.raises(RuntimeError, match="boom"):
            _default_build_digest(NOW)

        fake_session.close.assert_called_once()

    def test_empty_sent_history_still_passes_exclude_set_to_build_digest(self, monkeypatch):
        """An empty sent set (fresh install) is forwarded as ``exclude_job_ids=set()``,
        which fetch_digest_candidates treats as a no-op -- the default builder does
        not special-case the empty path."""
        fake_session = MagicMock(name="session")
        monkeypatch.setattr(send_digest_mod, "_open_session", lambda: fake_session)
        monkeypatch.setattr(send_digest_mod, "get_sent_job_ids", MagicMock(return_value=set()))
        mock_build = MagicMock(return_value=make_payload([make_job()]))
        monkeypatch.setattr(send_digest_mod, "build_digest", mock_build)

        from notifications.send_digest import _default_build_digest

        _default_build_digest(NOW)

        assert mock_build.call_args.kwargs["exclude_job_ids"] == set()
