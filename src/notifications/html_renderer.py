"""Pure HTML renderer for digest payloads.

Given a :class:`DigestPayload` produced by :func:`notifications.digest.select_digest`,
this module renders a clean, email-client-friendly HTML body string. It does NOT
send email, persist anything, touch NLP, the DB, or the network. The renderer is
pure: same payload -> same string, byte for byte.

Security contract -- job-board text is untrusted:

* Every field surfaced for display is escaped via :func:`html.escape` with
  ``quote=True`` (the default), neutralizing ``<``, ``>``, ``&``, ``"``, and
  ``'``. This covers title, company, location, site, description, match reasons,
  salary/currency, role group / location tier, and date strings.
* URLs are additionally scheme-checked (:data:`SAFE_URL_SCHEMES`). A job board
  link with a dangerous scheme (``javascript:``, ``data:``, ``vbscript:``, an
  unparseable/malformed URL such as an unclosed IPv6 literal, or a missing URL)
  is rendered as plain escaped text rather than a clickable ``<a>``. Only
  ``http``/``https`` URLs survive as hrefs, and even those are HTML-escaped in
  the ``href`` attribute so a crafted URL cannot break out of the attribute.
  Malformed inputs that make :func:`urllib.parse.urlsplit` raise ``ValueError``
  are caught and degrade the same way -- rendering never crashes on bad data.

Layout contract:

* Inline styles only (email clients strip ``<style>`` blocks / external CSS).
* No JavaScript, no external assets, no iframes.
* Semantic markup (``<h1>`` / ``<section>`` / ``<article>`` / lists) so screen
  readers and plain-text previews degrade gracefully.
* Selector order is preserved: the renderer iterates ``payload.jobs`` and
  ``payload.fallback_jobs`` as given and never re-sorts.
* A secondary "Other nearby options you may want to review" section is rendered
  below the primary list ONLY when ``payload.fallback_jobs`` is non-empty. When
  it is empty the section is omitted entirely so a strict-only digest looks
  exactly as before.

The function returns a ``<html>...</html>`` document string ready to be handed to
a future SES sender slice.
"""
from __future__ import annotations

import html
import logging
import math
import unicodedata
import urllib.parse

from notifications.digest import DigestJob, DigestPayload

logger = logging.getLogger(__name__)

# Truncate the full description to this many characters in the preview. The full
# description lives in the digest payload for a detail view later; the email only
# shows a preview so the card stays scannable.
DESCRIPTION_PREVIEW_MAX = 200

# Only these URL schemes are rendered as clickable hrefs. Anything else
# (javascript:, data:, vbscript:, or an unparsable URL) falls back to plain text
# so a bad/crafted URL can never execute or exfiltrate when the email is opened.
SAFE_URL_SCHEMES: tuple[str, ...] = ("http", "https")

# Characters that must never appear in a clickable href. ``urllib.parse.urlsplit``
# is permissive with malformed hosts such as ``"http://exa mple.com:abc"``: it
# preserves the embedded whitespace and bogus port, yielding a clickable href
# that points at a broken/crafted host. Rejecting raw ASCII control characters
# (0x00-0x1F) plus DEL (0x7F) and ASCII whitespace stops both malformed hosts
# and control-char obfuscation used to hide a URL from human review.
# range(0x21) covers control chars 0x00-0x1F plus the ASCII space (0x20).
_UNSAFE_URL_CHARS: frozenset[str] = frozenset(chr(c) for c in range(0x21)) | {"\x7f"}

# Unicode general categories that make a URL unsafe in any position. "C*" are
# control/format/surrogate codepoints (C0, C1 controls like NEL/next-line,
# BOM, etc.) and "Z*" are the Unicode separator categories (space, no-break
# space, line/paragraph separators). ``urlsplit`` keeps these verbatim inside a
# host or path, so a link such as ``"http://exa\u00a0mple.com/job"`` parses with
# an embedded NBSP and would render as a clickable href to a broken/crafted
# host. The ASCII frozenset above already covers the common cases; this check
# extends the rejection to the full Unicode whitespace/control surface so a
# non-ASCII obfuscation vector cannot slip past the ASCII-only guard.
_UNSAFE_URL_CATEGORIES: frozenset[str] = frozenset(
    # C*: control/format/surrogate/unassigned codepoints (C0 controls, C1
    # controls like NEL, BOM, etc.). Z*: Unicode separators (space, no-break
    # space, line/paragraph separators). ``urlsplit`` keeps these verbatim
    # inside a host or path, so a link with them cannot be a real href.
    ("Cc", "Cf", "Cs", "Co", "Cn", "Zs", "Zl", "Zp")
)

# Email layout constants. Inline styles keep the document self-contained for
# email clients that strip <style> blocks.
_CONTAINER_STYLE = (
    "font-family: Arial, Helvetica, sans-serif;"
    " max-width: 600px;"
    " margin: 0 auto;"
    " padding: 24px;"
    " color: #1a1a1a;"
)
_CARD_STYLE = (
    "border: 1px solid #e2e2e2;"
    " border-radius: 8px;"
    " padding: 16px 18px;"
    " margin-bottom: 16px;"
    " background: #ffffff;"
)
_BUTTON_STYLE = (
    "display: inline-block;"
    " padding: 8px 14px;"
    " background: #1a5fb4;"
    " color: #ffffff;"
    " border-radius: 4px;"
    " text-decoration: none;"
)
_MUTED_STYLE = "color: #5a5a5a; font-size: 13px;"
_PREVIEW_STYLE = "color: #3a3a3a; font-size: 14px; line-height: 1.45;"
_REASON_LIST_STYLE = "margin: 8px 0 0 0; padding-left: 20px; font-size: 13px;"

# Secondary fallback section. The heading is visually separated from the
# primary cards (top margin + a muted top border) so the lower-confidence tier
# reads as a distinct group, not a continuation of the primary list. The exact
# heading text is a product label -- do not rephrase it without product sign-off.
_FALLBACK_HEADING = "Other nearby options you may want to review"
_SECTION_HEADING_STYLE = (
    "margin: 28px 0 12px 0;"
    " padding-top: 12px;"
    " border-top: 1px solid #e2e2e2;"
    " font-size: 17px;"
    " color: #1a1a1a;"
)
_SECTION_INTRO_STYLE = "color: #5a5a5a; font-size: 13px; margin: 0 0 16px 0;"
# One-line context for the secondary tier so the subscriber understands why
# these are split from the primary list (lower title-confidence, still
# scorer-accepted nearby options). Kept short to avoid adding email noise.
_FALLBACK_INTRO = (
    "Lower-confidence matches that still fit the profile geography and role "
    "rules; review before applying."
)


def render_digest_html(payload: DigestPayload) -> str:
    """Render a digest payload as a self-contained HTML email body string.

    Args:
        payload: The :class:`DigestPayload` to render. Field order is preserved
            exactly as provided by the selector; the renderer never re-sorts.

    Returns:
        A complete ``<!DOCTYPE html>`` document string with inline styles, no
        external assets, and no JavaScript. Job-board text is HTML-escaped, and
        only ``http``/``https`` URLs become clickable.

    Raises:
        TypeError: If ``payload`` is not a :class:`DigestPayload`.
    """
    if not isinstance(payload, DigestPayload):
        raise TypeError(
            f"payload must be a DigestPayload, got {type(payload).__name__}"
        )

    # The email headline reports the TOTAL recommendation count (primary +
    # fallback) so the subject/H1 reflects everything the subscriber will see,
    # not just the strict tier. ``payload.count`` stays the primary-only count
    # in the data model; the renderer is the presentation authority here.
    total = payload.count + len(payload.fallback_jobs)

    if total == 0:
        body_html = _render_no_jobs()
    else:
        # Primary cards first, in selector order. When primary is empty but
        # fallback exists, no "no jobs" message is shown -- jobs DID match, just
        # at lower confidence, so the friendly empty state would be misleading.
        body_html = "".join(_render_job_card(job) for job in payload.jobs)
        if payload.fallback_jobs:
            body_html += _render_fallback_section(payload.fallback_jobs)

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f"<title>{html.escape(_subject(total))}</title>\n"
        "</head>\n"
        "<body>\n"
        f'<div style="{_CONTAINER_STYLE}">\n'
        f"<h1>{_header_text(total)}</h1>\n"
        f"{_subtitle(payload, total)}\n"
        f"{body_html}\n"
        "</div>\n"
        "</body>\n"
        "</html>"
    )


def _render_fallback_section(fallback_jobs: tuple[DigestJob, ...]) -> str:
    """Render the secondary lower-confidence tier under its distinct heading.

    Reuses :func:`_render_job_card` so a fallback row is visually identical to a
    primary row -- the separation is structural (heading + divider), not a
    different card style, so the subscriber can compare them at a glance. The
    heading text is a fixed product label; the intro line sets expectations
    without rephrasing it.

    Args:
        fallback_jobs: The secondary digest rows, already ranked by the selector.

    Returns:
        An HTML fragment: a section heading, a short intro, and one card per
        fallback job, in selector order.
    """
    cards = "".join(_render_job_card(job) for job in fallback_jobs)
    return (
        f'<h2 style="{_SECTION_HEADING_STYLE}">'
        f"{html.escape(_FALLBACK_HEADING)}</h2>\n"
        f'<p style="{_SECTION_INTRO_STYLE}">{html.escape(_FALLBACK_INTRO)}</p>\n'
        f"{cards}"
    )


def _subject(total: int) -> str:
    """Short plain-text subject line for the email header.

    Args:
        total: Total recommendation count (primary + fallback) shown in the
            subject so the inbox preview matches the email body.
    """
    return f"Industrial Bajio digest: {total} new job(s)"


def _header_text(total: int) -> str:
    """Top H1 of the email body.

    Args:
        total: Total recommendation count (primary + fallback).
    """
    return f"Industrial Bajio job digest ({total} new)"


def _subtitle(payload: DigestPayload, total: int) -> str:
    """Intro line under the header, escaping metadata fields.

    Reports the total recommendation count and, when a fallback tier exists,
    notes how it splits between primary and secondary so the subscriber can
    interpret the headline number.

    Args:
        payload: The digest payload being rendered.
        total: Total recommendation count (primary + fallback).
    """
    generated = _safe_date_only(payload.generated_at)
    niche = html.escape(payload.niche or "")
    profile = html.escape(payload.profile_name or "")
    fallback_count = len(payload.fallback_jobs)
    if fallback_count:
        split = (
            f" ({payload.count} top matches + {fallback_count} nearby options)"
        )
    else:
        split = ""
    return (
        f'<p style="{_MUTED_STYLE}">'
        f"{total} job(s){split} for the <strong>{niche}</strong> niche"
        f" (profile: {profile}), generated {generated},"
        f" freshness window {payload.freshness_days} day(s)."
        "</p>"
    )


def _render_no_jobs() -> str:
    """Friendly empty-state block used when no jobs were selected."""
    return (
        '<section style="text-align: center; padding: 32px 16px;">\n'
        "<p>No new jobs matched your alert profile today.</p>\n"
        '<p style="' + _MUTED_STYLE + '">'
        "New postings that fit the Industrial Bajio profile will appear here "
        "on the next digest.</p>\n"
        "</section>"
    )


def _render_job_card(job: DigestJob) -> str:
    """Build the HTML for a single job card, preserving selector order."""
    title = html.escape(job.title or "")
    company = html.escape(job.company or "")
    location = html.escape(job.location or "")
    site = html.escape(job.site or "")
    score = _format_score(job.score)
    salary = _format_salary(job.salary_min, job.salary_max, job.currency)
    date_only = _safe_date_only(job.date_scraped)
    link_html = _render_job_link(job)
    reasons_html = _render_match_reasons(job.match_reasons)
    preview = html.escape(_description_preview(job.description or ""))

    # The role group / location tier are low-risk scorer labels but are still
    # external-ish strings, so escape them defensively.
    role_group = html.escape(job.matched_role_group or "")
    location_tier = html.escape(job.location_tier or "")

    meta_parts: list[str] = []
    if company:
        meta_parts.append(f"<strong>{company}</strong>")
    if location:
        meta_parts.append(location)
    if site:
        meta_parts.append(f"via {site}")
    if salary:
        meta_parts.append(salary)
    meta_line = " &middot; ".join(meta_parts)

    sub_parts: list[str] = []
    if role_group or location_tier:
        labels = [p for p in (role_group, location_tier) if p]
        sub_parts.append("Fit: " + " / ".join(labels))
    sub_parts.append(score)
    sub_parts.append(f"Scraped {date_only}")
    sub_line = " &middot; ".join(html.escape(part) for part in sub_parts)

    return (
        f'<article style="{_CARD_STYLE}">\n'
        f"<h2 style=\"margin: 0 0 8px 0; font-size: 18px;\">{title}</h2>\n"
        f'<p style="{_MUTED_STYLE} margin: 0 0 10px 0;">{meta_line}</p>\n'
        f'<p style="{_MUTED_STYLE} margin: 0 0 12px 0;">{sub_line}</p>\n'
        f'<p style="{_PREVIEW_STYLE} margin: 0 0 12px 0;">{preview}</p>\n'
        f"{reasons_html}\n"
        f"{link_html}\n"
        "</article>"
    )


def _render_job_link(job: DigestJob) -> str:
    """Render the job URL as a styled button when safe, else as escaped text.

    A missing or unsafe URL (non-http(s) scheme, unparseable) is shown as plain
    text so a crafted/malformed link can never become an active href.
    """
    safe_url = _safe_url(job.job_url)
    if safe_url is None:
        label = html.escape(job.job_url or "(no link available)")
        return f'<p style="{_MUTED_STYLE} margin: 8px 0 0 0;">{label}</p>'

    escaped_href = html.escape(safe_url, quote=True)
    return (
        f'<p style="margin: 12px 0 0 0;">'
        f'<a href="{escaped_href}" target="_blank" '
        f'rel="noopener noreferrer" style="{_BUTTON_STYLE}">View posting</a>'
        "</p>"
    )


def _render_match_reasons(reasons: tuple[str, ...]) -> str:
    """Render the scorer's human-readable reasons as an escaped list."""
    if not reasons:
        return ""
    items = "".join(
        f"<li>{html.escape(reason)}</li>" for reason in reasons
    )
    return (
        f'<ul style="{_REASON_LIST_STYLE}">\n'
        f"{items}\n"
        "</ul>"
    )


def _format_score(score: int) -> str:
    """Return a short escaped label for the numeric score."""
    return f"Score {int(score)}"


def _format_salary(salary_min: float | None, salary_max: float | None, currency: str) -> str:
    """Format salary fields into a compact, HTML-safe string, or ``""`` when absent.

    Opts out entirely when both bounds are missing so an empty card meta line
    is not padded with a "salary not listed" placeholder that adds noise.

    The ``currency`` string originates from job-board data, so it is
    :func:`html.escape`'d here before being inserted into the meta line. The
    numeric amounts are produced by :func:`_format_amount` from floats, so they
    are inherently safe (digits/commas/period only); the currency is the only
    external substring surfaced, and this helper is its single escaping
    authority -- callers must NOT re-escape the returned string. Keeping the
    escape here (not at the call site) follows DRY: every renderer of salary
    text through this one function, so no consumer can forget to escape.
    """
    if salary_min is None and salary_max is None:
        return ""

    # Defense in depth: a NaN (Decimal('NaN') that slipped past the payload
    # coercion, or a float nan) is treated as absent so the card never shows
    # "Salary MXN nan - nan". The payload coercer normalizes NaN -> None, but a
    # renderer constructed by hand or a future field must not regress here.
    min_val = None if salary_min is None or math.isnan(salary_min) else salary_min
    max_val = None if salary_max is None or math.isnan(salary_max) else salary_max
    if min_val is None and max_val is None:
        return ""

    # Currency is job-board text; escape so a malicious code cannot inject tags.
    # Upper-casing happens before escaping so ">" etc. survive unchanged in form.
    cur = html.escape((currency or "").strip().upper())
    currency_prefix = f"{cur} " if cur else ""

    if min_val is not None and max_val is not None:
        return (
            f"Salary {currency_prefix}{_format_amount(min_val)}"
            f" - {_format_amount(max_val)}"
        )
    if min_val is not None:
        return f"Salary {currency_prefix}{_format_amount(min_val)}+"
    return f"Salary up to {currency_prefix}{_format_amount(max_val)}"


def _format_amount(value: float) -> str:
    """Format a salary number with thousands separators, dropping whole decimals.

    Salaries are whole pesos/dollars in practice; rendering ``25000`` not
    ``25000.0`` keeps the card compact.
    """
    amount = float(value)
    if amount.is_integer():
        return f"{int(amount):,}"
    return f"{amount:,}"


def _description_preview(description: str) -> str:
    """Collapse whitespace and truncate to :data:`DESCRIPTION_PREVIEW_MAX`.

    Email previews need to stay scannable; a multi-paragraph description is
    collapsed to a single line and capped, with an ellipsis when truncated.
    """
    collapsed = " ".join(description.split())
    if len(collapsed) <= DESCRIPTION_PREVIEW_MAX:
        return collapsed
    return collapsed[:DESCRIPTION_PREVIEW_MAX] + "\u2026"


def _safe_date_only(iso_string: str) -> str:
    """Return the YYYY-MM-DD portion of an ISO 8601 string, or a fallback.

    Validates the date prefix shape defensively; a malformed string falls back
    to "unknown date" rather than surfacing raw, unescaped text.
    """
    text = (iso_string or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return html.escape(text[:10])
    return "unknown date"


def _has_unsafe_chars(text: str) -> bool:
    """Return True if ``text`` contains ASCII or Unicode unsafe characters.

    Combines the ASCII whitespace/control frozenset with a Unicode general
    category check so non-ASCII obfuscation vectors (NBSP, line/paragraph
    separators, C1 controls like NEL) are rejected in addition to the legacy
    ASCII surface. ``str.isspace`` is intentionally NOT relied on alone because
    it misses several control codepoints that still break a clickable href.
    """
    if any(ch in _UNSAFE_URL_CHARS for ch in text):
        return True
    return any(unicodedata.category(ch) in _UNSAFE_URL_CATEGORIES for ch in text)


def _safe_url(url: str | None) -> str | None:
    """Return ``url`` when it is a well-formed http(s) link, else None.

    A malformed URL string (e.g. an unclosed IPv6 literal like ``"http://[::1"``,
    a host with embedded ASCII or Unicode whitespace like
    ``"http://exa mple.com:abc"`` or ``"http://exa\\u00a0mple.com/job"``, or an
    invalid port) is logged and treated as unsafe so a broken/tampered link
    degrades to plain text instead of either crashing the renderer or rendering
    a broken/crafted anchor.

    ``urlsplit`` is permissive: it keeps whitespace inside the host and a
    non-numeric port string without raising. We therefore also reject any raw
    ASCII or Unicode whitespace/control characters in the link and validate the
    port explicitly (accessing ``parsed.port`` raises ``ValueError`` on a bad
    port).

    The unsafe-character check runs against the RAW input, before any trimming.
    ``str.strip`` removes leading/trailing ASCII and Unicode whitespace (NBSP,
    line/paragraph separators, NEL, ASCII space), so checking after trimming
    would let a boundary obfuscation vector such as ``"\\u00a0https://example.com"``
    survive as a clickable href. Malformed inputs are never silently sanitized
    into a valid link -- they degrade to plain text.

    Raises:
        Nothing. ``urllib.parse.urlsplit`` raises ``ValueError`` on malformed
        URLs (notably incomplete IPv6 literals); that is caught here so
        rendering never crashes on bad source data.
    """
    if not url or not isinstance(url, str):
        return None
    # Check the RAW input for unsafe characters BEFORE any trimming. ``strip``
    # removes leading/trailing ASCII and Unicode whitespace (NBSP, line/paragraph
    # separators, NEL, ASCII space), so checking the trimmed value would hide a
    # boundary obfuscation vector such as "\u00a0https://example.com/job" and
    # let it render as a clickable href. Reject the raw value outright; a
    # malformed link is never silently sanitized into a valid one.
    if _has_unsafe_chars(url):
        logger.warning(
            "URL contains whitespace/control characters, treating as unsafe: %r", url
        )
        return None
    stripped = url.strip()
    try:
        parsed = urllib.parse.urlsplit(stripped)
    except ValueError:
        # "Invalid IPv6 URL" and similar: a corrupt source value must not take
        # down the whole digest render. Treat as unsafe -> plain text.
        logger.warning("Malformed URL rejected by parser: %r", url)
        return None
    if parsed.scheme.lower() not in SAFE_URL_SCHEMES:
        logger.warning("Unsafe/unsupported URL scheme rejected: %r", url)
        return None
    # A scheme with no netloc (e.g. "http:///path") is not a usable link.
    if not parsed.netloc:
        logger.warning("URL has no host, treating as unsafe: %r", url)
        return None
    # A non-numeric port string (":abc") does not make urlsplit raise, but
    # accessing ``parsed.port`` does. Validate explicitly so bogus ports degrade
    # to plain text instead of becoming a clickable href to a broken host.
    try:
        parsed.port  # noqa: B018 -- property access for its validation side effect
    except ValueError:
        logger.warning("URL has invalid port, treating as unsafe: %r", url)
        return None
    return stripped
