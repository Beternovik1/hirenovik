"""Local real-data preview generator for the Industrial Bajío alert digest.

Builds the actual digest from Supabase via
:func:`notifications.digest_repository.build_digest`, renders it to HTML via
:func:`notifications.html_renderer.render_digest_html`, and writes the result
to a local file for visual inspection.

This is NOT email sending. There is no SES, no SMTP, no NotificationLog, no
unsubscribe handling, and no network beyond the single DB read performed by
:func:`build_digest`. The generated HTML file is a local artifact for the
operator to open in a browser before the personalization/sender slices land.

Design contract:

* The public entry point :func:`generate_digest_preview` orchestrates three
  separable steps (build digest -> render HTML -> write file) and accepts
  injected callables for the first two so tests never touch a real database.
* DB I/O lives behind the default ``build_digest_fn``; it lazily opens a
  SQLAlchemy session from :func:`database.models.db_connect` only when the
  default path is taken. Importing this module never touches the database.
* Rendering and file writing stay pure from the DB: the renderer is already a
  pure function, and file writing is plain ``pathlib`` UTF-8 output.
* ``now`` is an explicit parameter so preview runs are reproducible; production
  / CLI use passes ``None`` which resolves to ``datetime.now(timezone.utc)``.

Run locally::

    PYTHONPATH=src python -m notifications.preview
    # or with an explicit output path:
    PYTHONPATH=src python -m notifications.preview --output /tmp/digest.html
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from database.models import db_connect
from notifications.digest import DigestPayload
from notifications.digest_repository import build_digest
from notifications.html_renderer import render_digest_html

logger = logging.getLogger(__name__)

# Default local preview output path. ``reports/`` is gitignored, so the
# generated HTML never gets committed accidentally. Overridable via the
# environment variable ``ALERT_DIGEST_PREVIEW_PATH`` for ad-hoc runs.
ALERT_DIGEST_PREVIEW_PATH: str = os.getenv(
    "ALERT_DIGEST_PREVIEW_PATH",
    "reports/industrial_bajio_digest_preview.html",
)
DEFAULT_PREVIEW_PATH: Path = Path(ALERT_DIGEST_PREVIEW_PATH)


def _open_session() -> Session:
    """Create a SQLAlchemy session bound to the configured Supabase engine.

    Lazily builds the engine via :func:`database.models.db_connect` so module
    import never opens a connection. A fresh session is returned; the caller is
    responsible for closing it (the default build callable does so in a
    ``finally`` block).
    """
    engine = db_connect()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


def _default_build_digest(now: datetime) -> DigestPayload:
    """Build the real Industrial Bajío digest from Supabase.

    Opens a short-lived session, delegates to
    :func:`notifications.digest_repository.build_digest` with the default
    profile/niche/freshness/limit, and always closes the session. Propagates
    any DB error to the caller; the preview is not silently faked.
    """
    session = _open_session()
    try:
        return build_digest(session, now)
    finally:
        session.close()


def generate_digest_preview(
    output_path: Path | str = DEFAULT_PREVIEW_PATH,
    now: datetime | None = None,
    *,
    build_digest_fn: Callable[[datetime], DigestPayload] | None = None,
    render_fn: Callable[[DigestPayload], str] | None = None,
) -> Path:
    """Build the Industrial Bajío digest and write a local HTML preview file.

    Orchestrates three steps:

    1. Build a :class:`DigestPayload` (real Supabase data by default, or an
       injected callable for tests).
    2. Render the payload to an HTML string via the pure renderer.
    3. Create any missing parent directories and write the HTML as UTF-8.

    Args:
        output_path: Destination file path. Parent directories are created on
            demand. Defaults to :data:`DEFAULT_PREVIEW_PATH`
            (``reports/industrial_bajio_digest_preview.html``).
        now: Reference datetime for the digest freshness window. ``None``
            resolves to ``datetime.now(timezone.utc)`` so the CLI run always
            uses the current instant. Passed positionally to
            ``build_digest_fn``.
        build_digest_fn: Callable ``(now: datetime) -> DigestPayload``. ``None``
            uses :func:`_default_build_digest`, which opens a real Supabase
            session. Inject a fake in tests to avoid the DB.
        render_fn: Callable ``(DigestPayload) -> str``. ``None`` uses
            :func:`notifications.html_renderer.render_digest_html`. Inject a
            fake in tests to isolate file-writing behavior from rendering.

    Returns:
        The :class:`pathlib.Path` the HTML was written to.

    Raises:
        Exception: Any error from the build or render step propagates; this
            function never silently swallows DB or I/O failures. A half-written
            file is avoided because writing happens only after render succeeds.
    """
    resolved_now = now if now is not None else datetime.now(UTC)
    build = build_digest_fn if build_digest_fn is not None else _default_build_digest
    render = render_fn if render_fn is not None else render_digest_html

    payload = build(resolved_now)
    html = render(payload)
    _validate_render_output(html)

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")

    logger.info(
        "Digest preview written: %d job(s) -> %s",
        payload.count,
        target,
    )
    return target


def _validate_render_output(html: str) -> None:
    """Fail fast on a non-string render result before touching the filesystem.

    A misconfigured ``render_fn`` returning ``None`` would otherwise produce a
    misleading ``TypeError`` deep inside :meth:`Path.write_text`; this guard
    surfaces the real contract violation at the orchestration boundary.
    """
    if not isinstance(html, str):
        raise TypeError(
            f"render_fn must return str, got {type(html).__name__}"
        )


def _cli() -> None:
    """Minimal CLI entry: parse ``--output`` and run one preview generation."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate a local Industrial Bajío digest HTML preview.",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=str(DEFAULT_PREVIEW_PATH),
        help=f"Destination HTML path (default: {DEFAULT_PREVIEW_PATH})",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    path = generate_digest_preview(output_path=args.output)
    logger.info("Preview ready at %s", path)


if __name__ == "__main__":
    _cli()
