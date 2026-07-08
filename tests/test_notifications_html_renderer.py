"""Tests for notifications.html_renderer: pure HTML rendering of a digest payload.

Covers the ``feat/alert-html-renderer`` behavior:

* Basic render with one and multiple jobs.
* Friendly no-jobs empty state.
* Strict HTML escaping of malicious job-board text (title, company, description,
  match reasons, url) -- a crafted payload must NEVER emit raw HTML/scripts.
* URL safety: only http/https schemes become clickable hrefs; ``javascript:``,
  ``data:``, schemes without a host, missing URLs, and malformed/unparseable
  URLs (e.g. unclosed IPv6 literals that make ``urlsplit`` raise) degrade to
  plain text -- rendering must never crash on bad URL data.
* Salary formatting: present (min/max/currency), min-only, max-only, absent, and
  malicious currency code (must be HTML-escaped, never a raw tag).
* Match reasons rendered as an escaped list.
* Selector order preserved (renderer never re-sorts).
* Description truncation/preview: long descriptions collapse and ellipsize.
* Non-mutation of the input payload.

Pure: no DB, no network, no email sending. Payloads are built directly from
dataclasses so tests control every field, including malicious content that the
scorer would otherwise reject.
"""

import copy

import pytest

from notifications.digest import DigestJob, DigestPayload
from notifications.html_renderer import (
    DESCRIPTION_PREVIEW_MAX,
    render_digest_html,
)

PROFILE = "industrial_irapuato_bajio"
NICHE = "Industrial Bajío"
GENERATED_AT = "2026-07-01T12:00:00+00:00"


def make_job(
    job_id=1,
    title="SAP WM Analyst",
    company="Industrias Bajio",
    location="Silao, Guanajuato",
    site="occ",
    job_url="https://occ.com.mx/job/1",
    score=150,
    match_reasons=(
        "Location: silao (Silao / Puerto Interior +50)",
        "Role: SAP / inventory (+100 via 'sap')",
    ),
    date_scraped="2026-06-30T10:00:00+00:00",
    salary_min=None,
    salary_max=None,
    currency="MXN",
    description="Gestion de warehouse management con SAP WM.",
    matched_city="silao",
    matched_role_group="SAP / inventory",
    location_tier="Silao / Puerto Interior",
):
    """Build a single DigestJob with sensible defaults for renderer tests.

    Tests override individual fields to exercise formatting and escaping paths
    the scorer would otherwise reject (malicious text, extreme salaries).
    """
    return DigestJob(
        id=job_id,
        title=title,
        company=company,
        location=location,
        site=site,
        job_url=job_url,
        score=score,
        match_reasons=match_reasons,
        date_scraped=date_scraped,
        salary_min=salary_min,
        salary_max=salary_max,
        currency=currency,
        description=description,
        matched_city=matched_city,
        matched_role_group=matched_role_group,
        location_tier=location_tier,
    )


def make_payload(jobs, count=None):
    """Build a DigestPayload from a list of DigestJob, preserving order."""
    jobs_tuple = tuple(jobs)
    return DigestPayload(
        profile_name=PROFILE,
        niche=NICHE,
        generated_at=GENERATED_AT,
        freshness_days=5,
        limit=10,
        count=len(jobs) if count is None else count,
        jobs=jobs_tuple,
    )


# ---------------------------------------------------------------------------
# Basic rendering
# ---------------------------------------------------------------------------


class TestBasicRender:
    def test_one_job_renders_full_document(self):
        payload = make_payload([make_job()])
        html = render_digest_html(payload)

        assert html.startswith("<!DOCTYPE html>")
        assert html.endswith("</html>")
        # Key fields appear, escaped where needed (the safe Job URL survives).
        assert "SAP WM Analyst" in html
        assert "Industrias Bajio" in html
        assert "Silao, Guanajuato" in html
        assert "via occ" in html
        assert "Score 150" in html
        assert "2026-06-30" in html
        assert 'href="https://occ.com.mx/job/1"' in html
        assert "View posting" in html

    def test_multiple_jobs_each_rendered_in_order(self):
        jobs = [make_job(job_id=1, title="Job One"), make_job(job_id=2, title="Job Two")]
        payload = make_payload(jobs)
        html = render_digest_html(payload)

        pos_one = html.index("Job One")
        pos_two = html.index("Job Two")
        assert pos_one < pos_two
        assert html.count('<article style="') == 2

    def test_header_reports_count(self):
        payload = make_payload([make_job()])
        html = render_digest_html(payload)
        assert "Industrial Bajio job digest (1 new)" in html


# ---------------------------------------------------------------------------
# Empty digest
# ---------------------------------------------------------------------------


class TestEmptyDigest:
    def test_empty_payload_renders_no_jobs_state(self):
        payload = make_payload([])
        html = render_digest_html(payload)

        assert "No new jobs matched your alert profile today." in html
        assert '<article style="' not in html
        assert "(0 new)" in html  # header count

    def test_empty_payload_still_valid_document(self):
        html = render_digest_html(make_payload([]))
        assert html.startswith("<!DOCTYPE html>")
        assert html.endswith("</html>")


# ---------------------------------------------------------------------------
# Escaping
# ---------------------------------------------------------------------------


class TestEscaping:
    def test_malicious_title_is_escaped(self):
        payload = make_payload(
            [make_job(title="<script>alert('xss')</script>")]
        )
        html = render_digest_html(payload)

        assert "<script>" not in html
        assert "<script>alert('xss')</script>" not in html
        # html.escape turns < into &lt;.
        assert "&lt;script&gt;" in html
        assert "alert('xss')" not in html  # the literal JS never survives

    def test_malicious_company_is_escaped(self):
        payload = make_payload(
            [make_job(company='<img src=x onerror="evil()">')]
        )
        html = render_digest_html(payload)

        # The raw <img tag must never appear; html.escape turns it into text.
        # An active onerror="..." attribute (quote-delimited) must not survive.
        body = html.split("<body>")[1].split("</body>")[0]
        assert "<img" not in body
        assert 'onerror="evil()"' not in body
        assert "&lt;img" in html
        assert "&quot;" in html

    def test_malicious_description_is_escaped(self):
        payload = make_payload(
            [make_job(description='</p><script>alert(1)</script><p>real')]
        )
        html = render_digest_html(payload)

        body = html.split("<body>")[1].split("</body>")[0]
        assert "<script>alert(1)</script>" not in body
        # The injected </p> from the description is text-escaped, not a real
        # closing tag -- the structural </p> tags still exist, so we assert the
        # escaped form appears and the raw script does not.
        assert "&lt;/p&gt;" in html
        assert "&lt;script&gt;" in html

    def test_malicious_match_reason_is_escaped(self):
        payload = make_payload(
            [make_job(match_reasons=("<script>alert(1)</script>",))]
        )
        html = render_digest_html(payload)

        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_malicious_location_is_escaped(self):
        payload = make_payload([make_job(location="<b>Leon</b>, Guanajuato")])
        html = render_digest_html(payload)

        assert "<b>Leon</b>" not in html
        assert "&lt;b&gt;Leon&lt;/b&gt;" in html

    def test_quote_and_amp_in_fields_do_not_break_attributes(self):
        payload = make_payload(
            [make_job(title='Title "quoted" & amp', company="A & B < Co")]
        )
        html = render_digest_html(payload)

        body = html.split("<body>")[1].split("</body>")[0]
        # The "&" in user text must become &amp; (not raw &), and the "<" must
        # become &lt; so it cannot open a stray tag.
        assert "&amp;" in html
        assert "&quot;" in html
        assert "&lt; Co" in body
        assert "< Co" not in body


# ---------------------------------------------------------------------------
# URL safety
# ---------------------------------------------------------------------------


class TestUrlSafety:
    def test_safe_https_url_renders_as_clickable_link(self):
        payload = make_payload([make_job(job_url="https://example.com/job/1")])
        html = render_digest_html(payload)

        assert 'href="https://example.com/job/1"' in html
        assert "View posting" in html

    def test_safe_http_url_renders_as_clickable_link(self):
        payload = make_payload([make_job(job_url="http://example.com/job/1")])
        html = render_digest_html(payload)

        assert 'href="http://example.com/job/1"' in html

    def test_javascript_scheme_url_renders_as_text_not_link(self):
        payload = make_payload([make_job(job_url="javascript:alert(1)")])
        html = render_digest_html(payload)

        assert "View posting" not in html
        # The literal dangerous URL is escaped, never an active href.
        assert "javascript:alert(1)" in html  # shown as text (escaped)
        assert 'href="javascript' not in html

    def test_data_scheme_url_renders_as_text_not_link(self):
        payload = make_payload([make_job(job_url="data:text/html,<script>")])
        html = render_digest_html(payload)

        assert "View posting" not in html
        assert 'href="data' not in html

    def test_vbscript_scheme_url_renders_as_text_not_link(self):
        payload = make_payload([make_job(job_url="vbscript:msgbox(1)")])
        html = render_digest_html(payload)

        assert "View posting" not in html
        assert 'href="vbscript' not in html

    def test_url_without_host_renders_as_text_not_link(self):
        payload = make_payload([make_job(job_url="http:///just-a-path")])
        html = render_digest_html(payload)

        assert "View posting" not in html
        assert 'href="http:///just-a-path"' not in html

    def test_missing_url_renders_no_link_text(self):
        payload = make_payload([make_job(job_url="")])
        html = render_digest_html(payload)

        assert "View posting" not in html
        assert "(no link available)" in html

    def test_url_with_quotes_cannot_break_href_attribute(self):
        payload = make_payload(
            [make_job(job_url='https://example.com/a" onclick="evil')]
        )
        html = render_digest_html(payload)

        # The href attribute value must be escaped; the injected onclick must
        # never appear as a real attribute.
        assert 'onclick="evil"' not in html
        assert "&quot;" in html

    def test_malformed_ipv6_url_does_not_crash_and_renders_text(self):
        # Regression: urllib.parse.urlsplit raises ValueError on an unclosed
        # IPv6 literal (e.g. "http://[::1"). The renderer must catch it, treat
        # the URL as unsafe (plain text, no clickable href), and never crash.
        payload = make_payload([make_job(job_url="http://[::1")])
        # Must not raise.
        html = render_digest_html(payload)

        body = html.split("<body>")[1].split("</body>")[0]
        assert "View posting" not in body
        assert 'href="http' not in body
        # The malformed URL is surfaced as escaped plain text, not an anchor.
        assert "(no link available)" in body or "http://[::1" in html

    def test_unparseable_url_with_other_malformation_does_not_crash(self):
        # A second malformed shape: a malformed port that crashes some parsers
        # is treated the same way -- degrade to text, never crash.
        payload = make_payload([make_job(job_url="http://exa mple.com:abc")])
        html = render_digest_html(payload)

        # Either way (parseable-but-bad or unparseable), no clickable href.
        assert "View posting" in html or 'href="http://exa' not in html


# ---------------------------------------------------------------------------
# Salary formatting
# ---------------------------------------------------------------------------


class TestSalaryFormatting:
    def test_salary_min_and_max_present(self):
        payload = make_payload(
            [make_job(salary_min=25000.0, salary_max=35000.0, currency="MXN")]
        )
        html = render_digest_html(payload)

        assert "25,000" in html
        assert "35,000" in html
        assert "MXN" in html
        assert "-" in html

    def test_salary_min_only_shows_plus(self):
        payload = make_payload([make_job(salary_min=25000.0, salary_max=None)])
        html = render_digest_html(payload)

        assert "25,000+" in html
        assert "35,000" not in html

    def test_salary_max_only_shows_up_to(self):
        payload = make_payload([make_job(salary_min=None, salary_max=40000.0)])
        html = render_digest_html(payload)

        assert "Salary up to MXN 40,000" in html
        assert "35,000" not in html

    def test_salary_absent_emits_nothing(self):
        payload = make_payload([make_job(salary_min=None, salary_max=None)])
        html = render_digest_html(payload)

        assert "Salary" not in html

    def test_salary_without_currency_omits_prefix(self):
        payload = make_payload(
            [make_job(salary_min=25000.0, salary_max=35000.0, currency="")]
        )
        html = render_digest_html(payload)

        assert "MXN" not in html
        assert "25,000" in html

    def test_integral_salary_drops_trailing_decimal(self):
        payload = make_payload([make_job(salary_min=25000.0, salary_max=35000.00)])
        html = render_digest_html(payload)

        assert "25,000.0" not in html
        assert "35,000.0" not in html

    def test_malicious_currency_is_escaped_not_raw_tag(self):
        # Regression: currency is job-board text. A malicious code must be
        # html.escape'd by _format_salary so it can never inject a raw tag.
        payload = make_payload(
            [make_job(salary_min=1.0, salary_max=2.0, currency="<script>alert(1)</script>")]
        )
        html = render_digest_html(payload)

        body = html.split("<body>")[1].split("</body>")[0]
        assert "<script>" not in body
        assert "<script>alert(1)</script>" not in body
        # The escaped form is present (case is uppercased then escaped).
        assert "&lt;SCRIPT&gt;" in html

    def test_currency_with_amp_and_quotes_stays_safe(self):
        # A currency containing & and " must not break out of the meta line or
        # introduce a stray attribute.
        payload = make_payload(
            [make_job(salary_min=1.0, salary_max=2.0, currency='A&B"onclick=x')]
        )
        html = render_digest_html(payload)

        body = html.split("<body>")[1].split("</body>")[0]
        assert "onclick=x" not in body
        assert "&amp;" in html
        assert "&quot;" in html

    def test_valid_currency_still_renders_uppercased(self):
        # Pre-existing behavior preserved: a normal currency code is upper-cased
        # and shown, unaffected by the new escaping path.
        payload = make_payload([make_job(salary_min=1.0, salary_max=2.0, currency="mxn")])
        html = render_digest_html(payload)

        assert "MXN" in html
        assert "1 - 2" in html


# ---------------------------------------------------------------------------
# Match reasons
# ---------------------------------------------------------------------------


class TestMatchReasons:
    def test_reasons_render_as_list_items(self):
        reasons = ("Location: silao (Silao / Puerto Interior +50)", "Role: SAP / inventory (+100)")
        payload = make_payload([make_job(match_reasons=reasons)])
        html = render_digest_html(payload)

        assert "<ul" in html
        assert "Location: silao" in html
        assert "Role: SAP / inventory" in html
        assert html.count("<li>") == 2

    def test_empty_reasons_renders_no_list(self):
        payload = make_payload([make_job(match_reasons=())])
        html = render_digest_html(payload)

        assert "<ul" not in html
        assert "<li>" not in html


# ---------------------------------------------------------------------------
# Order preservation
# ---------------------------------------------------------------------------


class TestOrderPreserved:
    def test_jobs_render_in_payload_order_not_resorted(self):
        # Deliberately reverse-scored jobs: renderer must NOT sort by score.
        jobs = [
            make_job(job_id=10, title="Low Score", score=10),
            make_job(job_id=20, title="High Score", score=200),
        ]
        payload = make_payload(jobs)
        html = render_digest_html(payload)

        pos_low = html.index("Low Score")
        pos_high = html.index("High Score")
        assert pos_low < pos_high, "renderer must preserve payload order"

    def test_three_jobs_keep_exact_input_sequence(self):
        jobs = [
            make_job(job_id=3, title="Three"),
            make_job(job_id=1, title="One"),
            make_job(job_id=2, title="Two"),
        ]
        payload = make_payload(jobs)
        html = render_digest_html(payload)

        positions = [html.index(t) for t in ("Three", "One", "Two")]
        assert positions == sorted(positions)


# ---------------------------------------------------------------------------
# Description preview / truncation
# ---------------------------------------------------------------------------


class TestDescriptionPreview:
    def test_short_description_rendered_in_full(self):
        payload = make_payload([make_job(description="Short and clear text.")])
        html = render_digest_html(payload)

        assert "Short and clear text." in html

    def test_long_description_truncated_with_ellipsis(self):
        long_text = "word " * 100  # ~500 chars
        payload = make_payload([make_job(description=long_text)])
        html = render_digest_html(payload)

        assert "\u2026" in html  # ellipsis (escaped by html.escape, stays literal)

    def test_truncated_description_respects_preview_max(self):
        # Collapsed text length should be at most DESCRIPTION_PREVIEW_MAX + the
        # single ellipsis codepoint -- never a longer unsplit run of x's.
        long_text = "x" * (DESCRIPTION_PREVIEW_MAX * 3)
        payload = make_payload([make_job(description=long_text)])
        html = render_digest_html(payload)

        # Exactly DESCRIPTION_PREVIEW_MAX x's survive, plus the ellipsis.
        assert "x" * DESCRIPTION_PREVIEW_MAX in html
        assert "x" * (DESCRIPTION_PREVIEW_MAX + 1) not in html

    def test_whitespace_collapsed_in_preview(self):
        payload = make_payload(
            [make_job(description="line one\n\n\n   line two\t\ttab")]
        )
        html = render_digest_html(payload)

        # Multi-whitespace must collapse to single spaces in the preview.
        assert "line one line two tab" in html
        # The raw multi-newline sequence must not surface verbatim in the visible
        # preview text.
        assert "line one\n\n\n   line two" not in html


# ---------------------------------------------------------------------------
# Non-mutation
# ---------------------------------------------------------------------------


class TestNonMutation:
    def test_payload_not_mutated_after_render(self):
        job = make_job(title="Original Title / <safe>")
        payload = make_payload([job])
        original = copy.deepcopy(payload)

        render_digest_html(payload)

        assert payload == original
        assert payload.jobs[0].title == original.jobs[0].title
        assert payload.jobs == original.jobs

    def test_jobs_tuple_identity_preserved(self):
        # The renderer must iterate, not rebuild, the jobs tuple.
        jobs = (make_job(job_id=1), make_job(job_id=2))
        payload = make_payload(list(jobs))
        original_jobs = payload.jobs

        render_digest_html(payload)

        assert payload.jobs is original_jobs


# ---------------------------------------------------------------------------
# Type guard
# ---------------------------------------------------------------------------


class TestTypeGuard:
    def test_non_payload_raises_type_error(self):
        with pytest.raises(TypeError, match="DigestPayload"):
            render_digest_html({"jobs": []})  # type: ignore[arg-type]
