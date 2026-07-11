"""Tests for notifications.preview: local real-data digest HTML preview generation.

Covers the ``feat/alert-email-preview`` behavior:

* Writes rendered HTML to the target path.
* Creates missing parent directories on demand.
* Calls ``build_digest_fn`` then ``render_fn`` in the right order.
* Empty digest still writes a valid empty-state HTML file.
* Output path can be overridden.
* ``now`` defaults to an aware UTC instant when ``None``.
* No SES/SMTP/email-sending imports are introduced by the preview module.
* Default DB-backed builder opens a session, delegates to build_digest, and
  closes the session on success or failure.
* Errors from DB/build/render steps propagate rather than being swallowed.
* The returned path matches the requested output.

No real database is touched. Tests for the default Supabase/session path patch
``db_connect``, ``sessionmaker``, and ``build_digest`` at the preview module
boundary so the CLI contract is covered without network or DB access. The
forbidden-imports test inspects the module source so the no-sending guarantee is
static and regression-proof.
"""

import inspect
from datetime import UTC, datetime

import pytest

import notifications.preview as preview
from notifications.digest import DigestJob, DigestPayload
from notifications.html_renderer import render_digest_html
from notifications.preview import generate_digest_preview

PROFILE = "industrial_irapuato_bajio"
NICHE = "Industrial Bajío"
GENERATED_AT = "2026-07-01T12:00:00+00:00"


def make_job(job_id=1, title="SAP WM Analyst"):
    """Build a single DigestJob with minimal defaults for preview tests."""
    return DigestJob(
        id=job_id,
        title=title,
        company="Industrias Bajio",
        location="Silao, Guanajuato",
        site="occ",
        job_url="https://example.com/job/1",
        score=150,
        match_reasons=("Location: silao (+50)", "Role: SAP / inventory (+100)"),
        date_scraped="2026-06-30T10:00:00+00:00",
        salary_min=25000.0,
        salary_max=35000.0,
        currency="MXN",
        description="Gestion de warehouse management con SAP WM.",
        matched_city="silao",
        matched_role_group="SAP / inventory",
        location_tier="Silao / Puerto Interior",
    )


def make_payload(jobs, count=None, fallback_jobs=None):
    """Build a DigestPayload from a list of DigestJob.

    ``fallback_jobs`` defaults to empty so existing primary-only tests are
    unaffected; pass a list to exercise the secondary section in the preview.
    """
    jobs_tuple = tuple(jobs)
    fallback_tuple = tuple(fallback_jobs) if fallback_jobs is not None else ()
    return DigestPayload(
        profile_name=PROFILE,
        niche=NICHE,
        generated_at=GENERATED_AT,
        freshness_days=5,
        limit=10,
        count=len(jobs) if count is None else count,
        jobs=jobs_tuple,
        fallback_jobs=fallback_tuple,
    )


class _Recorder:
    """Captures call order and arguments across injected callables."""

    def __init__(self):
        self.calls = []


class _FakeSession:
    """Small session double that records whether ``close`` was called."""

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def builder_returning(jobs, recorder=None, *, now_received=None, fallback_jobs=None):
    """Build a fake build_digest_fn returning a payload from ``jobs``.

    Optionally records the ``now`` it received for the default-clock test, and
    optionally carries ``fallback_jobs`` so the preview's rendering of the
    secondary section can be exercised end-to-end through the real renderer.
    """

    def _build(now):
        if recorder is not None:
            recorder.calls.append("build")
        if now_received is not None:
            now_received.append(now)
        return make_payload(jobs, fallback_jobs=fallback_jobs)

    return _build


def real_renderer_with_recorder(recorder=None):
    """Wrap the real renderer to record call order without changing output."""

    def _render(payload):
        if recorder is not None:
            recorder.calls.append("render")
        return render_digest_html(payload)

    return _render


# ---------------------------------------------------------------------------
# File writing
# ---------------------------------------------------------------------------


class TestWritesHtml:
    def test_writes_rendered_html_to_target_path(self, tmp_path):
        out = tmp_path / "preview.html"
        build = builder_returning([make_job()])
        render = real_renderer_with_recorder()

        result = generate_digest_preview(
            output_path=out, now=datetime(2026, 7, 1, tzinfo=UTC),
            build_digest_fn=build, render_fn=render,
        )

        assert result == out
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert content.startswith("<!DOCTYPE html>")
        assert content.endswith("</html>")
        assert "SAP WM Analyst" in content

    def test_empty_digest_writes_empty_state_html(self, tmp_path):
        out = tmp_path / "empty.html"
        build = builder_returning([])
        render = real_renderer_with_recorder()

        generate_digest_preview(
            output_path=out, now=datetime(2026, 7, 1, tzinfo=UTC),
            build_digest_fn=build, render_fn=render,
        )

        content = out.read_text(encoding="utf-8")
        assert "No new jobs matched your alert profile today." in content
        assert "<!DOCTYPE html>" in content
        assert "(0 new)" in content


class TestParentDirs:
    def test_creates_missing_parent_directories(self, tmp_path):
        nested = tmp_path / "reports" / "subdir" / "deep"
        out = nested / "preview.html"
        build = builder_returning([make_job()])
        render = real_renderer_with_recorder()

        generate_digest_preview(
            output_path=out, now=datetime(2026, 7, 1, tzinfo=UTC),
            build_digest_fn=build, render_fn=render,
        )

        assert out.exists()
        assert nested.is_dir()


class TestOutputOverride:
    def test_output_path_can_be_overridden(self, tmp_path):
        default = tmp_path / "default.html"
        custom = tmp_path / "custom.html"
        build = builder_returning([make_job()])
        render = real_renderer_with_recorder()

        generate_digest_preview(
            output_path=custom, now=datetime(2026, 7, 1, tzinfo=UTC),
            build_digest_fn=build, render_fn=render,
        )

        assert custom.exists()
        assert not default.exists()


class TestCallOrder:
    def test_build_called_before_render(self, tmp_path):
        recorder = _Recorder()
        out = tmp_path / "preview.html"
        build = builder_returning([make_job()], recorder=recorder)
        render = real_renderer_with_recorder(recorder=recorder)

        generate_digest_preview(
            output_path=out, now=datetime(2026, 7, 1, tzinfo=UTC),
            build_digest_fn=build, render_fn=render,
        )

        assert recorder.calls == ["build", "render"]


class TestDefaultNow:
    def test_now_none_uses_aware_utc_instant(self, tmp_path):
        out = tmp_path / "preview.html"
        received: list[datetime] = []
        build = builder_returning([], now_received=received)
        render = real_renderer_with_recorder()

        generate_digest_preview(
            output_path=out, now=None,
            build_digest_fn=build, render_fn=render,
        )

        assert len(received) == 1
        instant = received[0]
        assert instant.tzinfo is not None
        assert instant.utcoffset() is not None


# ---------------------------------------------------------------------------
# Default DB-backed builder path
# ---------------------------------------------------------------------------


class TestDefaultBuildDigestPath:
    def test_default_build_digest_opens_session_delegates_and_closes(
        self, monkeypatch
    ):
        now = datetime(2026, 7, 1, tzinfo=UTC)
        engine = object()
        session = _FakeSession()
        payload = make_payload([make_job()])
        calls = []

        def fake_db_connect():
            calls.append("db_connect")
            return engine

        def fake_sessionmaker(*, bind, expire_on_commit):
            calls.append(("sessionmaker", bind, expire_on_commit))

            def factory():
                calls.append("session_factory")
                return session

            return factory

        def fake_build_digest(received_session, received_now):
            calls.append(("build_digest", received_session, received_now))
            return payload

        monkeypatch.setattr(preview, "db_connect", fake_db_connect)
        monkeypatch.setattr(preview, "sessionmaker", fake_sessionmaker)
        monkeypatch.setattr(preview, "build_digest", fake_build_digest)

        result = preview._default_build_digest(now)

        assert result is payload
        assert session.closed is True
        assert calls == [
            "db_connect",
            ("sessionmaker", engine, False),
            "session_factory",
            ("build_digest", session, now),
        ]

    def test_default_build_digest_closes_session_when_build_fails(
        self, monkeypatch
    ):
        now = datetime(2026, 7, 1, tzinfo=UTC)
        session = _FakeSession()

        def fake_sessionmaker(*, bind, expire_on_commit):
            return lambda: session

        def fake_build_digest(received_session, received_now):
            raise RuntimeError("query failed")

        monkeypatch.setattr(preview, "db_connect", lambda: object())
        monkeypatch.setattr(preview, "sessionmaker", fake_sessionmaker)
        monkeypatch.setattr(preview, "build_digest", fake_build_digest)

        with pytest.raises(RuntimeError, match="query failed"):
            preview._default_build_digest(now)

        assert session.closed is True

    def test_generate_preview_uses_default_builder_when_not_injected(
        self, tmp_path, monkeypatch
    ):
        now = datetime(2026, 7, 1, tzinfo=UTC)
        out = tmp_path / "preview.html"
        payload = make_payload([make_job()])
        calls = []

        def fake_default_build_digest(received_now):
            calls.append(("default_build", received_now))
            return payload

        def fake_render(received_payload):
            calls.append(("render", received_payload))
            return "<html>preview</html>"

        monkeypatch.setattr(preview, "_default_build_digest", fake_default_build_digest)

        result = generate_digest_preview(
            output_path=out,
            now=now,
            render_fn=fake_render,
        )

        assert result == out
        assert out.read_text(encoding="utf-8") == "<html>preview</html>"
        assert calls == [("default_build", now), ("render", payload)]


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    def test_build_error_propagates(self, tmp_path):
        out = tmp_path / "preview.html"

        def _boom(now):
            raise RuntimeError("db down")

        with pytest.raises(RuntimeError, match="db down"):
            generate_digest_preview(
                output_path=out, now=datetime(2026, 7, 1, tzinfo=UTC),
                build_digest_fn=_boom, render_fn=real_renderer_with_recorder(),
            )

        assert not out.exists()

    def test_render_error_propagates(self, tmp_path):
        out = tmp_path / "preview.html"

        def _boom_render(payload):
            raise ValueError("render failed")

        with pytest.raises(ValueError, match="render failed"):
            generate_digest_preview(
                output_path=out, now=datetime(2026, 7, 1, tzinfo=UTC),
                build_digest_fn=builder_returning([make_job()]),
                render_fn=_boom_render,
            )

        assert not out.exists()

    def test_non_string_render_output_raises_before_write(self, tmp_path):
        out = tmp_path / "preview.html"

        with pytest.raises(TypeError, match="render_fn must return str"):
            generate_digest_preview(
                output_path=out, now=datetime(2026, 7, 1, tzinfo=UTC),
                build_digest_fn=builder_returning([make_job()]),
                render_fn=lambda payload: None,
            )

        assert not out.exists()


# ---------------------------------------------------------------------------
# No sending imports / side effects (static guarantee)
# ---------------------------------------------------------------------------


class TestNoSendingImports:
    @pytest.mark.parametrize(
        "forbidden",
        [
            "import boto3",
            "from boto3",
            "import smtplib",
            "from smtplib",
            "send_email",
            "smtp",
        ],
    )
    def test_preview_module_source_has_no_send_or_ses_or_smtp(self, forbidden, tmp_path):
        # Static, regression-proof: inspect the actual source shipped. A future
        # edit that sneaks in a sender import or an SMTP call is caught here.
        from notifications import preview

        source = inspect.getsource(preview)
        assert forbidden not in source, (
            f"preview module must not introduce '{forbidden}' (no email sending)"
        )

    def test_preview_module_does_not_import_ses_or_smtp_packages(self):
        # Runtime guard: importing the preview module must not pull in
        # smtplib (SES/SMTP sending). smtplib absent from sys.modules after a
        # fresh import of notifications.preview proves the module is send-free
        # at import time; smtplib is otherwise not a dep of any import chain
        # used here.
        # Fresh import of the module under test (it may already be cached).
        import importlib
        import sys

        import notifications.preview

        importlib.reload(notifications.preview)

        assert "smtplib" not in sys.modules


# ---------------------------------------------------------------------------
# Secondary fallback section in the preview output
# ---------------------------------------------------------------------------


class TestFallbackSectionPreview:
    """The preview surfaces the secondary section when the built payload carries
    fallback jobs, and omits it otherwise. The preview itself does no rendering
    logic -- it forwards to the real renderer -- so these tests prove the
    end-to-end build -> render -> write path for the two-tier payload."""

    def test_preview_shows_fallback_section_when_fallback_jobs_exist(
        self, tmp_path
    ):
        out = tmp_path / "preview.html"
        build = builder_returning(
            [make_job(job_id=1, title="Primary Job")],
            fallback_jobs=[make_job(job_id=2, title="Fallback Job")],
        )

        generate_digest_preview(
            output_path=out, now=datetime(2026, 7, 1, tzinfo=UTC),
            build_digest_fn=build, render_fn=real_renderer_with_recorder(),
        )

        content = out.read_text(encoding="utf-8")
        assert "Other nearby options you may want to review" in content
        assert "Fallback Job" in content
        assert "Primary Job" in content

    def test_preview_omits_fallback_section_when_no_fallback_jobs(
        self, tmp_path
    ):
        out = tmp_path / "preview.html"
        build = builder_returning([make_job(job_id=1, title="Primary Job")])

        generate_digest_preview(
            output_path=out, now=datetime(2026, 7, 1, tzinfo=UTC),
            build_digest_fn=build, render_fn=real_renderer_with_recorder(),
        )

        content = out.read_text(encoding="utf-8")
        assert "Other nearby options you may want to review" not in content
        assert "Primary Job" in content


# ---------------------------------------------------------------------------
# Return value contract
# ---------------------------------------------------------------------------


class TestReturnValue:
    def test_returns_path_object_matching_request(self, tmp_path):
        out = tmp_path / "preview.html"
        result = generate_digest_preview(
            output_path=out, now=datetime(2026, 7, 1, tzinfo=UTC),
            build_digest_fn=builder_returning([make_job()]),
            render_fn=real_renderer_with_recorder(),
        )
        assert isinstance(result, type(out))
        assert result == out
