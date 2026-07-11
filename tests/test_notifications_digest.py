"""Tests for notifications.digest: deterministic Industrial Bajío digest selector.

Covers the ``feat/alert-digest-selection`` behavior:

* Eligibility hard-filter: niche == "Industrial Bajío", status == "NEW",
  description present and non-empty, date_scraped within the freshness window,
  and CV-fit via score_job (wrong geography / reject keywords / no role signal
  are excluded).
* Ranking: score descending, date_scraped descending, id ascending (freshness is
  a filter, NOT a sort tier -- stale jobs are excluded, not deprioritized).
* Limit cap (default 10), zero, and the negative-limit guard.
* Payload fields and JSON serializability (Decimal salary -> float, ISO
  date_scraped, match_reasons).
* Empty input and no-eligible-jobs behavior.
* Non-mutation of input.
* Profile resolution: None resolves the default profile; an unregistered profile
  raises ValueError.
* Digest-only strong-signal gate: a strong non-weak growth role-group OR
  non-trade include keyword must appear in the TITLE itself (not in the
  description and not in the career alone -- the email digest headline is the
  title). Career-only signals (e.g. career ``Ingeniero Industrial`` with an
  unrelated title) are rejected; low-priority industrial-trades keywords in the
  title are weak and need an accompanying growth keyword. The scorer/matcher/
  profiles stay broad for the enrichment bucket.

Pure: no DB, no network. Job rows are SimpleNamespace doubles mirroring the ORM
Job shape, the same pattern used in tests/test_enrichment_priority.py.
"""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from notifications.digest import (
    DIGEST_DEFAULT_FALLBACK_LIMIT,
    DIGEST_DEFAULT_LIMIT,
    DigestJob,
    DigestPayload,
    _low_priority_trade_keywords,
    payload_to_dict,
    select_digest,
)
from notifications.profiles import (
    INDUSTRIAL_IRAPUATO_BAJIO_PROFILE,
    INDUSTRIAL_IRAPUATO_BAJIO_ROLE_GROUPS,
    RoleGroup,
)
from notifications.scoring import score_job

PROFILE = INDUSTRIAL_IRAPUATO_BAJIO_PROFILE
ALERT_NICHE = "Industrial Bajío"
_UTC = timezone.utc

# Fixed reference time so every freshness assertion is deterministic. Chosen as
# midday so day-boundary math is never ambiguous.
NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=_UTC)


def make_job(
    job_id,
    title="SAP WM Analyst",
    raw_location="Silao, Guanajuato",
    description="Gestion de warehouse management con SAP WM.",
    industry_niche=ALERT_NICHE,
    status="NEW",
    days_ago=1,
    company="Industrias Bajio",
    site="occ",
    job_url=None,
    salary_min=None,
    salary_max=None,
    currency="MXN",
):
    """Build a mutable Job-like object with every attribute the selector touches.

    Defaults describe a fully eligible, top-score (150) job: Silao tier 1 (50) +
    SAP/inventory role group (100). Individual tests override fields to exercise
    rejection paths. Uses SimpleNamespace so tests can freely read attributes
    exactly like the ORM path does, without a real SQLAlchemy model.
    """
    return SimpleNamespace(
        id=job_id,
        site=site,
        job_url=job_url or f"https://example.com/job/{job_id}",
        title=title,
        company=company,
        raw_location=raw_location,
        country="Mexico",
        country_code="MX",
        state="Guanajuato",
        career=title,
        scraped_by="test",
        industry_niche=industry_niche,
        job_type="presencial",
        salary_min=salary_min,
        salary_max=salary_max,
        currency=currency,
        description=description,
        date_scraped=NOW - timedelta(days=days_ago),
        last_updated=None,
        status=status,
    )


def _ids(payload):
    """Extract the ordered id list from a payload for ranking assertions."""
    return [job.id for job in payload.jobs]


def _fallback_ids(payload):
    """Extract the ordered id list from the payload's fallback tier."""
    return [job.id for job in payload.fallback_jobs]


# ---------------------------------------------------------------------------
# Eligibility: each rule independently excludes a job
# ---------------------------------------------------------------------------


class TestEligibility:
    def test_fully_eligible_job_is_selected(self):
        job = make_job(1)
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        assert payload.count == 1
        assert _ids(payload) == [1]

    def test_wrong_niche_is_excluded(self):
        job = make_job(1, industry_niche="Ingenieria de Datos")
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        assert payload.count == 0

    def test_non_new_status_is_excluded(self):
        for status in ("PENDING_ENRICHMENT", "NOTIFIED", "ORPHANED"):
            job = make_job(1, status=status)
            payload = select_digest([job], NOW, profile=PROFILE, limit=10)
            assert payload.count == 0, f"status {status} should be excluded"

    def test_null_description_is_excluded(self):
        job = make_job(1, description=None)
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        assert payload.count == 0

    def test_empty_description_is_excluded(self):
        job = make_job(1, description="")
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        assert payload.count == 0

    def test_whitespace_only_description_is_excluded(self):
        job = make_job(1, description="   \n\t  ")
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        assert payload.count == 0

    def test_stale_job_is_excluded(self):
        # freshness_days=5, job scraped 6 days ago -> outside the window.
        job = make_job(1, days_ago=6)
        payload = select_digest([job], NOW, profile=PROFILE, freshness_days=5, limit=10)

        assert payload.count == 0

    def test_freshness_boundary_is_inclusive(self):
        # Exactly 5 days old with freshness_days=5 -> (NOW - scraped) == cutoff,
        # and the <= comparison must include it.
        job = make_job(1, days_ago=5)
        payload = select_digest([job], NOW, profile=PROFILE, freshness_days=5, limit=10)

        assert payload.count == 1

    def test_scorer_rejected_wrong_geography_is_excluded(self):
        # Queretaro is outside the allowed Guanajuato cities; score_job rejects.
        job = make_job(1, raw_location="Queretaro, Queretaro", title="SAP WM Analyst")
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        assert payload.count == 0

    def test_scorer_rejected_internship_keyword_is_excluded(self):
        # "becario" is an exclude keyword; score_job returns None.
        job = make_job(1, title="Becario SAP WM", description="Programa de becario.")
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        assert payload.count == 0

    def test_scorer_rejected_unpaid_is_excluded(self):
        # "sin remuneracion" is a reject keyword; score_job returns None.
        job = make_job(
            1, title="Operador", description="Puesto sin remuneracion, voluntario."
        )
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        assert payload.count == 0

    def test_scorer_rejected_no_role_signal_is_excluded(self):
        # An allowed-city job with no industrial role keyword: the scorer rejects
        # it (no relevance signal), so it must NOT surface in the digest even
        # though it passes every column rule.
        job = make_job(
            1, title="Recepcionista", raw_location="Silao, Guanajuato",
            description="Atencion al cliente en oficinas.",
        )
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        assert payload.count == 0

    def test_missing_date_scraped_is_excluded_as_stale(self):
        job = make_job(1)
        job.date_scraped = None
        payload = select_digest([job], NOW, profile=PROFILE, freshness_days=5, limit=10)

        assert payload.count == 0


# ---------------------------------------------------------------------------
# Ranking: score desc, date_scraped desc, id asc (NO freshness sort tier)
# ---------------------------------------------------------------------------


class TestRanking:
    def test_score_descending(self):
        high = make_job(1, title="SAP WM Analyst", raw_location="Silao, Guanajuato")  # 150
        low = make_job(
            2,
            title="Inspector de Calidad",
            raw_location="Irapuato, Guanajuato",
            description="Inspeccion de calidad en planta automotriz.",
        )  # 90
        payload = select_digest([low, high], NOW, profile=PROFILE, limit=10)

        assert _ids(payload) == [1, 2]

    def test_date_scraped_descending_breaks_score_tie(self):
        # Same score (150), different recency -> newer first.
        newer = make_job(1, days_ago=1)
        older = make_job(2, days_ago=2)
        payload = select_digest([older, newer], NOW, profile=PROFILE, limit=10)

        assert _ids(payload) == [1, 2]

    def test_id_ascending_is_final_tiebreaker(self):
        # Same score AND same date_scraped -> id ascending.
        same_date = NOW - timedelta(days=1)
        a = make_job(2, days_ago=1)
        b = make_job(1, days_ago=1)
        a.date_scraped = same_date
        b.date_scraped = same_date
        payload = select_digest([a, b], NOW, profile=PROFILE, limit=10)

        assert _ids(payload) == [1, 2]

    def test_full_three_criteria_order(self):
        """End-to-end ranking (all jobs fresh & eligible):

          A id=1 SAP WM @ Silao  score 150, scraped 1d ago
          B id=2 SAP WM @ Silao  score 150, scraped 2d ago (older than A)
          C id=3 Quality @ Irap  score 90,  scraped 1d ago
        Expected: A, B, C.
        """
        a = make_job(1, title="SAP WM Analyst", raw_location="Silao, Guanajuato", days_ago=1)
        b = make_job(2, title="SAP WM Specialist", raw_location="Silao, Guanajuato", days_ago=2)
        c = make_job(
            3,
            title="Inspector de Calidad",
            raw_location="Irapuato, Guanajuato",
            description="Inspeccion de calidad en planta automotriz.",
            days_ago=1,
        )
        payload = select_digest([c, b, a], NOW, profile=PROFILE, limit=10)

        assert _ids(payload) == [1, 2, 3]

    def test_deterministic_across_runs(self):
        jobs = [
            make_job(3, title="SAP WM Analyst", raw_location="Silao, Guanajuato", days_ago=2),
            make_job(1, title="Operador", raw_location="Irapuato, Guanajuato", days_ago=1),
            make_job(2, title="SAP WM", raw_location="Salamanca, Guanajuato", days_ago=1),
        ]
        first = select_digest(jobs, NOW, profile=PROFILE, limit=10)
        second = select_digest(jobs, NOW, profile=PROFILE, limit=10)

        assert _ids(first) == _ids(second)


# ---------------------------------------------------------------------------
# Future date_scraped: eligible (fresh) but ranking capped at now
# ---------------------------------------------------------------------------


class TestFutureTimestampHandling:
    def test_future_dated_job_is_still_eligible(self):
        """A job scraped slightly in the future (clock skew) is recent, so it
        passes the freshness eligibility gate rather than being dropped."""
        job = make_job(1)
        job.date_scraped = NOW + timedelta(hours=1)
        payload = select_digest([job], NOW, profile=PROFILE, freshness_days=5, limit=10)

        assert payload.count == 1

    def test_future_dated_job_does_not_outrank_legitimate_now_job(self):
        """A far-future date_scraped must NOT dominate a job scraped exactly at
        now. Both clamp to now for ranking, so id ascending breaks the tie."""
        future = make_job(2)
        future.date_scraped = NOW + timedelta(days=365)
        legit = make_job(1)
        legit.date_scraped = NOW
        payload = select_digest([future, legit], NOW, profile=PROFILE, limit=10)

        # Same score, both rank as now -> id ascending: 1 before 2.
        assert _ids(payload) == [1, 2]

    def test_future_dated_job_does_not_outrank_higher_score_legitimate_job(self):
        """The ranking cap prevents a future-dated low-score job from using its
        inflated timestamp to jump ahead of a higher-score legitimate job. Score
        remains the primary ranking key regardless of the clamped timestamp."""
        future_low = make_job(
            2,
            title="Inspector de Calidad",
            raw_location="Irapuato, Guanajuato",
            description="Inspeccion de calidad en planta automotriz.",
        )
        future_low.date_scraped = NOW + timedelta(days=365)
        legit_high = make_job(
            1, title="SAP WM Analyst", raw_location="Silao, Guanajuato", days_ago=1
        )
        payload = select_digest([future_low, legit_high], NOW, profile=PROFILE, limit=10)

        # Score still wins: 150 > 90 regardless of the clamped timestamp.
        assert _ids(payload) == [1, 2]

    def test_two_future_dated_jobs_rank_by_id_when_clamped_equal(self):
        """Two equal-score jobs both scraped in the future clamp to now, so id
        ascending is the sole discriminator -- they do not sort by their
        (irrelevant) future timestamps."""
        far = make_job(2)
        far.date_scraped = NOW + timedelta(days=365)
        near = make_job(1)
        near.date_scraped = NOW + timedelta(hours=1)
        payload = select_digest([far, near], NOW, profile=PROFILE, limit=10)

        assert _ids(payload) == [1, 2]

    def test_future_job_date_scraped_reported_as_actual_in_payload(self):
        """The payload reports the ACTUAL stored date_scraped (not the clamped
        value) so a renderer shows what the DB holds; only ranking uses the cap."""
        job = make_job(1)
        future = NOW + timedelta(days=10)
        job.date_scraped = future
        payload = select_digest([job], NOW, profile=PROFILE, freshness_days=20, limit=10)

        assert payload.jobs[0].date_scraped == aware_utc_check(future).isoformat()


# ---------------------------------------------------------------------------
# Limit
# ---------------------------------------------------------------------------


class TestLimit:
    def test_limit_caps_result_count(self):
        jobs = [make_job(i) for i in range(1, 6)]  # 5 eligible, equal score/date
        payload = select_digest(jobs, NOW, profile=PROFILE, limit=2)

        assert payload.count == 2
        # Equal score+date -> id ascending, so the first two ids surface.
        assert _ids(payload) == [1, 2]
        assert payload.limit == 2

    def test_limit_zero_returns_empty(self):
        jobs = [make_job(1)]
        payload = select_digest(jobs, NOW, profile=PROFILE, limit=0)

        assert payload.count == 0
        assert payload.jobs == ()

    def test_limit_negative_returns_empty(self):
        """Negative limit must NOT wrap to tail elements (the slice footgun)."""
        jobs = [make_job(i) for i in range(1, 4)]
        payload = select_digest(jobs, NOW, profile=PROFILE, limit=-1)

        assert payload.count == 0
        assert payload.jobs == ()
        # limit is clamped to 0 in the reported metadata.
        assert payload.limit == 0

    def test_default_limit_constant_is_ten(self):
        # The product contract: default digest cap is 10. Asserted at the
        # constant level so an accidental config change is caught here.
        assert DIGEST_DEFAULT_LIMIT == 10

    def test_more_than_limit_yields_only_top_ranked(self):
        # 12 eligible jobs, limit=10 -> only the 10 highest-scoring surface.
        jobs = [
            make_job(i, title="SAP WM Analyst", raw_location="Silao, Guanajuato")
            for i in range(1, 13)
        ]
        payload = select_digest(jobs, NOW, profile=PROFILE, limit=10)

        assert payload.count == 10
        assert _ids(payload) == list(range(1, 11))


# ---------------------------------------------------------------------------
# Payload fields and serializability
# ---------------------------------------------------------------------------


class TestPayload:
    def test_payload_has_required_fields(self):
        job = make_job(1)
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        assert payload.count == 1
        digest_job = payload.jobs[0]
        assert isinstance(digest_job, DigestJob)
        assert digest_job.id == 1
        assert digest_job.title == "SAP WM Analyst"
        assert digest_job.company == "Industrias Bajio"
        assert digest_job.location == "Silao, Guanajuato"
        assert digest_job.site == "occ"
        assert digest_job.job_url == "https://example.com/job/1"
        assert digest_job.score == 150
        assert digest_job.description
        assert digest_job.matched_city == "silao"
        assert "SAP / inventory" in digest_job.matched_role_group
        assert digest_job.location_tier == "Silao / Puerto Interior"

    def test_match_reasons_are_included(self):
        job = make_job(1)
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        reasons = payload.jobs[0].match_reasons
        assert isinstance(reasons, tuple)
        assert any("Location" in reason for reason in reasons)
        assert any("Role" in reason for reason in reasons)

    def test_date_scraped_is_iso_string(self):
        job = make_job(1, days_ago=1)
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        iso = payload.jobs[0].date_scraped
        assert isinstance(iso, str)
        # Round-trips back to the original aware UTC datetime.
        assert datetime.fromisoformat(iso) == aware_utc_check(job.date_scraped)

    def test_salary_decimal_fields_become_float(self):
        job = make_job(1, salary_min=Decimal("25000.00"), salary_max=Decimal("35000.00"))
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        digest_job = payload.jobs[0]
        assert digest_job.salary_min == 25000.0
        assert digest_job.salary_max == 35000.0
        assert isinstance(digest_job.salary_min, float)
        assert digest_job.currency == "MXN"

    def test_decimal_nan_salary_fields_become_none(self):
        """DB Decimal('NaN') salary values must not leak into the digest payload."""
        job = make_job(1, salary_min=Decimal("NaN"), salary_max=Decimal("NaN"))
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        assert payload.jobs[0].salary_min is None
        assert payload.jobs[0].salary_max is None

    def test_salary_fields_none_when_absent(self):
        job = make_job(1, salary_min=None, salary_max=None)
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        assert payload.jobs[0].salary_min is None
        assert payload.jobs[0].salary_max is None

    def test_payload_is_json_serializable(self):
        """asdict + json.dumps must succeed (the renderer/sender contract)."""
        job = make_job(1, salary_min=Decimal("25000.00"))
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        data = payload_to_dict(payload)
        # No Decimal, no datetime, no SimpleNamespace leaks into the dict.
        serialized = json.dumps(data)
        assert json.loads(serialized)["count"] == 1
        assert json.loads(serialized)["jobs"][0]["salary_min"] == 25000.0

    def test_payload_metadata(self):
        job = make_job(1)
        payload = select_digest(
            [job], NOW, profile=PROFILE, niche=ALERT_NICHE, freshness_days=5, limit=10
        )

        assert payload.profile_name == "industrial_irapuato_bajio"
        assert payload.niche == ALERT_NICHE
        assert payload.freshness_days == 5
        assert payload.limit == 10
        assert payload.count == 1
        assert isinstance(payload, DigestPayload)
        # generated_at round-trips to NOW (aware UTC).
        assert datetime.fromisoformat(payload.generated_at) == NOW


# ---------------------------------------------------------------------------
# Empty / no-eligible behavior
# ---------------------------------------------------------------------------


class TestEmpty:
    def test_empty_input_returns_empty_payload(self):
        payload = select_digest([], NOW, profile=PROFILE, limit=10)

        assert payload.count == 0
        assert payload.jobs == ()
        assert payload.fallback_jobs == ()

    def test_no_eligible_jobs_returns_empty_payload(self):
        jobs = [
            make_job(1, industry_niche="Tech"),
            make_job(2, status="NOTIFIED"),
            make_job(3, description=""),
        ]
        payload = select_digest(jobs, NOW, profile=PROFILE, limit=10)

        assert payload.count == 0
        assert payload.jobs == ()
        assert payload.fallback_jobs == ()


# ---------------------------------------------------------------------------
# Non-mutation
# ---------------------------------------------------------------------------


class TestNonMutation:
    def test_input_order_and_content_not_mutated(self):
        jobs = [
            make_job(2, title="Operador", raw_location="Irapuato, Guanajuato"),
            make_job(1, title="SAP WM", raw_location="Silao, Guanajuato"),
        ]
        original_ids = [j.id for j in jobs]
        original_statuses = [j.status for j in jobs]

        select_digest(jobs, NOW, profile=PROFILE, limit=10)

        assert [j.id for j in jobs] == original_ids
        assert [j.status for j in jobs] == original_statuses


# ---------------------------------------------------------------------------
# Profile resolution
# ---------------------------------------------------------------------------


class TestProfileResolution:
    def test_profile_none_resolves_default(self):
        job = make_job(1)
        payload = select_digest([job], NOW, profile=None, limit=10)

        # The default profile is the industrial Bajio one, so the job is selected.
        assert payload.count == 1
        assert payload.profile_name == "industrial_irapuato_bajio"

    def test_explicit_profile_is_used(self):
        job = make_job(1)
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        assert payload.profile_name == PROFILE.name

    def test_unregistered_default_profile_raises_value_error(self):
        """If the default profile name resolves to None, the digest must fail
        loudly rather than silently surfacing unranked jobs."""
        job = make_job(1)
        with patch("notifications.digest.get_alert_profile", return_value=None):
            with pytest.raises(ValueError, match="Alert profile"):
                select_digest([job], NOW, profile=None, limit=10)


# ---------------------------------------------------------------------------
# Digest-only strong-signal gate
# ---------------------------------------------------------------------------


class TestDigestStrongSignalGate:
    def test_rejects_unrelated_title_when_only_description_has_generic_keyword(self):
        """Regression: ING. ELECTRICO should not enter email only because the
        description contains a generic quality/manufacturing keyword."""
        job = make_job(
            1,
            title="ING. ELECTRICO",
            raw_location="Celaya, Guanajuato",
            description=(
                "Ejecutar ordenes de mantenimiento de manera segura, con calidad, "
                "en tiempo y forma."
            ),
        )
        job.career = "Ingeniero Electrico"

        assert score_job(_to_record(job), PROFILE) is not None
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        # Primary stays strict: the gate-rejected job is NOT in the headline
        # tier. It surfaces in the lower-confidence fallback section instead.
        assert payload.count == 0
        assert _fallback_ids(payload) == [1]

    def test_rejects_ing_electrico_career_ingeniero_industrial(self):
        """Regression (verbatim DB row): title ``ING. ELECTRICO`` with career
        ``Ingeniero Industrial`` and a description-only ``calidad`` mention must
        NOT enter the digest. The scorer accepts it (quality group via the
        description keyword), but the email digest headline is the title, and the
        title carries no growth role-group keyword -- the career-only
        ``ingeniero industrial`` signal is too coarse for a digest entry under
        the title-required rule."""
        job = make_job(
            1,
            title="ING. ELECTRICO",
            raw_location="Celaya, Guanajuato",
            description=(
                "Ejecutar ordenes de mantenimiento de manera segura, con "
                "calidad, en tiempo y forma."
            ),
        )
        job.career = "Ingeniero Industrial"

        # Sanity: the scorer accepts via the description-only 'calidad' keyword
        # (description also matches the trades include 'mantenimiento'), so the
        # rejection is digest-local, not a scorer rejection.
        assert score_job(_to_record(job), PROFILE) is not None
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        # Primary stays strict: the gate-rejected job is NOT in the headline
        # tier. It surfaces in the lower-confidence fallback section instead.
        assert payload.count == 0
        assert _fallback_ids(payload) == [1]

    def test_rejects_unrelated_title_with_career_only_growth_signal(self):
        """An unrelated title must NOT enter the digest on a career-only growth
        signal. ``Recepcionista`` carries no industrial role keyword in its title,
        but career ``Ingeniero Industrial`` would have satisfied the old
        title-or-career gate. Under the title-required rule the career is
        ignored and the job is rejected even though the scorer accepts it via a
        description-only include keyword."""
        job = make_job(
            1,
            title="Recepcionista",
            raw_location="Silao, Guanajuato",
            # Description carries an include keyword so the scorer accepts the
            # job (the rejection is digest-local, not scorer-side).
            description="Actitud de servicio y calidad en atencion al area.",
        )
        job.career = "Ingeniero Industrial"

        assert score_job(_to_record(job), PROFILE) is not None
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        # Primary stays strict: the gate-rejected job is NOT in the headline
        # tier. It surfaces in the lower-confidence fallback section instead.
        assert payload.count == 0
        assert _fallback_ids(payload) == [1]

    def test_growth_keyword_in_career_alone_does_not_promote_unrelated_title(self):
        """A growth role-group keyword ('calidad') present ONLY in the career
        must not promote a title that otherwise carries no strong signal. The
        old title-or-career gate would have let this through; title-required
        behavior rejects it."""
        job = make_job(
            1,
            title="Electricista",
            raw_location="Silao, Guanajuato",
            # Description carries 'calidad' so the scorer accepts via the
            # quality group; the title hit is only the weak trade 'electricista'.
            description="Instalaciones electricas con calidad en planta.",
        )
        job.career = "Ingeniero de Calidad"

        assert score_job(_to_record(job), PROFILE) is not None
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        # Primary stays strict: the gate-rejected job is NOT in the headline
        # tier. It surfaces in the lower-confidence fallback section instead.
        assert payload.count == 0
        assert _fallback_ids(payload) == [1]

    def test_accepts_strong_title_even_when_description_wins_higher_group(self):
        """A strong title/career signal should pass even if description contains
        a higher-priority keyword that wins the scorer group."""
        job = make_job(
            1,
            title="Almacenista",
            raw_location="Irapuato, Guanajuato",
            description="Experiencia con SAP y control de materiales.",
        )
        job.career = "Almacenista"

        assert score_job(_to_record(job), PROFILE) is not None
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        assert payload.count == 1
        assert _ids(payload) == [1]

    def test_almacen_title_include_keyword_signal_is_accepted(self):
        """Regression: bare ``Almacen`` is a scorer-accepted include keyword that
        is NOT part of any role group. A title/career hit on it must satisfy the
        digest strong-signal gate rather than being dropped because the role
        groups only contain the compound forms (``auxiliar de almacen`` etc.)."""
        job = make_job(
            1,
            title="Almacen",
            raw_location="Irapuato, Guanajuato",
            description="Encargado del almacén y control de stock.",
        )
        job.career = "Almacen"

        assert score_job(_to_record(job), PROFILE) is not None
        # Sanity: bare "almacen" is the include-keyword signal, not a role-group
        # keyword, so it would be dropped by the pre-fix role-groups-only gate.
        assert score_job(_to_record(job), PROFILE)[
            "matched_keyword"
        ] == "almacen"
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        assert payload.count == 1
        assert _ids(payload) == [1]

    def test_produccion_title_include_keyword_signal_is_accepted(self):
        """Regression: bare ``Produccion`` is a scorer-accepted include keyword
        that is NOT part of any role group (only compound forms
        ``operador de produccion`` / ``programacion de la produccion`` are). A
        title/career hit on bare ``produccion`` must satisfy the digest gate."""
        job = make_job(
            1,
            title="Produccion",
            raw_location="Salamanca, Guanajuato",
            description="Apoyo a la línea de producción en planta.",
        )
        job.career = "Produccion"

        assert score_job(_to_record(job), PROFILE) is not None
        assert score_job(_to_record(job), PROFILE)[
            "matched_keyword"
        ] == "produccion"
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        assert payload.count == 1
        assert _ids(payload) == [1]

    def test_selected_jobs_are_subset_of_score_job_accepts(self):
        """The digest selector is stricter than score_job: selected jobs must be
        scorer-accepted, but scorer-accepted weak description-only jobs may be
        rejected by the digest-only strong title/career gate."""
        accepted = make_job(1, title="SAP WM Analyst", raw_location="Silao, Guanajuato")
        rejected_geo = make_job(2, title="SAP WM Analyst", raw_location="Queretaro, Queretaro")
        rejected_role = make_job(
            3, title="Recepcionista", raw_location="Silao, Guanajuato",
            description="Atencion al cliente.",
        )

        assert score_job(_to_record(accepted), PROFILE) is not None
        assert score_job(_to_record(rejected_geo), PROFILE) is None
        assert score_job(_to_record(rejected_role), PROFILE) is None

        payload = select_digest(
            [accepted, rejected_geo, rejected_role], NOW, profile=PROFILE, limit=10
        )
        assert _ids(payload) == [1]
        # Scorer-rejected jobs are NOT fallback candidates either: there is no
        # fit signal at all, so neither the primary nor the secondary tier
        # surfaces them.
        assert _fallback_ids(payload) == []

    def test_rejects_ing_electrico_when_career_has_trade_keyword(self):
        """Regression: ING. ELECTRICO must not enter the email digest when its
        only title/career signal is a low-priority industrial-trades keyword
        (maintenance / electrical), even though the scorer accepts it via a
        description-only ``calidad`` mention. The trades group is the
        subscriber's valid-but-not-growth path, so a trade-only title/career
        signal is too weak for a daily email."""
        job = make_job(
            1,
            title="ING. ELECTRICO",
            raw_location="Celaya, Guanajuato",
            description=(
                "Ejecutar ordenes de mantenimiento de manera segura, con calidad, "
                "en tiempo y forma. Electricista industrial."
            ),
        )
        job.career = "Mantenimiento Electrico"

        # Sanity: the scorer accepts (quality group via description 'calidad'),
        # so the rejection is digest-local, not a scorer rejection.
        assert score_job(_to_record(job), PROFILE) is not None
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        # Primary stays strict: the gate-rejected job is NOT in the headline
        # tier. It surfaces in the lower-confidence fallback section instead.
        assert payload.count == 0
        assert _fallback_ids(payload) == [1]

    def test_rejects_ing_electrico_when_career_is_electricista(self):
        """A bare trade noun (``electricista``) in career is also a weak signal;
        the digest gate must reject when no growth keyword accompanies it."""
        job = make_job(
            1,
            title="ING. ELECTRICO",
            raw_location="Celaya, Guanajuato",
            description="Mantenimiento electrico industrial con calidad.",
        )
        job.career = "Electricista"

        assert score_job(_to_record(job), PROFILE) is not None
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        # Primary stays strict: the gate-rejected job is NOT in the headline
        # tier. It surfaces in the lower-confidence fallback section instead.
        assert payload.count == 0
        assert _fallback_ids(payload) == [1]

    def test_rejects_pure_trade_title_when_description_has_calidad(self):
        """A pure trades title (``Mantenimiento``) with a description-only
        ``calidad`` mention is scorer-accepted but digest-rejected: the only
        title/career signal is a weak trade keyword."""
        job = make_job(
            1,
            title="Mantenimiento",
            raw_location="Salamanca, Guanajuato",
            description="Mantenimiento preventivo y correctivo con calidad.",
        )
        job.career = "Mantenimiento"

        assert score_job(_to_record(job), PROFILE) is not None
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        # Primary stays strict: the gate-rejected job is NOT in the headline
        # tier. It surfaces in the lower-confidence fallback section instead.
        assert payload.count == 0
        assert _fallback_ids(payload) == [1]

    def test_rejects_pure_welding_trade_title(self):
        """Another trades bucket (welding / ``Soldador``) is also weak and must
        not enter the digest on a trade-only title/career signal."""
        job = make_job(
            1,
            title="Soldador",
            raw_location="Silao, Guanajuato",
            description="Soldadura MIG/MAG con calidad en planta.",
        )
        job.career = "Soldador"

        assert score_job(_to_record(job), PROFILE) is not None
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        # Primary stays strict: the gate-rejected job is NOT in the headline
        # tier. It surfaces in the lower-confidence fallback section instead.
        assert payload.count == 0
        assert _fallback_ids(payload) == [1]

    def test_trade_title_with_growth_signal_in_title_is_accepted(self):
        """A trades job that ALSO carries a growth role-group keyword in
        title/career must still pass: the gate rejects trade-ONLY signals, not
        trades jobs that additionally show a growth signal. ``SAP`` is a growth
        (SAP/inventory) role-group keyword, so ``Electricista con SAP`` passes
        even though ``electricista`` is a weak trade token."""
        job = make_job(
            1,
            title="Electricista con SAP",
            raw_location="Silao, Guanajuato",
            description="Mantenimiento electrico y SAP WM en planta.",
        )
        job.career = "Electricista con SAP"

        assert score_job(_to_record(job), PROFILE) is not None
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        assert payload.count == 1
        assert _ids(payload) == [1]

    def test_tecnico_de_calidad_growth_signal_passes_despite_weak_tecnico(self):
        """``tecnico`` is a weak trade token, but ``tecnico de calidad`` is a
        growth (quality) role-group keyword. A title carrying the compound growth
        keyword must pass: the gate skips the weak bare token but still honors
        the growth compound keyword that contains it."""
        job = make_job(
            1,
            title="Tecnico de Calidad",
            raw_location="Irapuato, Guanajuato",
            description="Inspeccion de calidad en linea de produccion.",
        )
        job.career = "Tecnico de Calidad"

        assert score_job(_to_record(job), PROFILE) is not None
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        assert payload.count == 1
        assert _ids(payload) == [1]

    def test_inventory_warehouse_title_jobs_remain_accepted(self):
        """Preserve contract: inventory/warehouse title jobs accepted by the
        scorer must remain accepted by the digest gate. ``inventarios`` is a
        growth (SAP/inventory) role-group keyword; bare ``almacen`` is a
        non-trade include keyword. Neither is a weak trade token."""
        inventarios = make_job(
            1,
            title="Analista de Inventarios de Almacen",
            raw_location="Irapuato, Guanajuato",
            description="Control de inventarios y operaciones de almacen.",
        )
        inventarios.career = "Analista de Inventarios de Almacen"

        encargado = make_job(
            2,
            title="Encargado Almacen y Reparto",
            raw_location="Irapuato, Guanajuato",
            description="Encargado del almacen, reparto y control de stock.",
        )
        encargado.career = "Encargado Almacen y Reparto"

        assert score_job(_to_record(inventarios), PROFILE) is not None
        assert score_job(_to_record(encargado), PROFILE) is not None
        payload = select_digest(
            [inventarios, encargado], NOW, profile=PROFILE, limit=10
        )

        assert _ids(payload) == [1, 2]

    def test_quality_inspector_title_jobs_remain_accepted(self):
        """Preserve contract: quality inspector title jobs must remain accepted.
        ``calidad`` / ``inspector de calidad`` are growth (quality) role-group
        keywords, not weak trade tokens."""
        short_title = make_job(
            1,
            title="Inspector Calidad",
            raw_location="Salamanca, Guanajuato",
            description="Inspeccion de calidad en planta automotriz.",
        )
        short_title.career = "Inspector Calidad"

        long_title = make_job(
            2,
            title="Inspector de Calidad",
            raw_location="Celaya, Guanajuato",
            description="Inspeccion y control de calidad en linea.",
        )
        long_title.career = "Inspector de Calidad"

        assert score_job(_to_record(short_title), PROFILE) is not None
        assert score_job(_to_record(long_title), PROFILE) is not None
        payload = select_digest(
            [short_title, long_title], NOW, profile=PROFILE, limit=10
        )

        assert _ids(payload) == [1, 2]


# ---------------------------------------------------------------------------
# Secondary fallback section (lower-confidence scorer-accepted candidates)
# ---------------------------------------------------------------------------


def make_fallback_job(
    job_id,
    title="Soldador",
    raw_location="Silao, Guanajuato",
    description="Soldadura MIG/MAG con calidad en planta.",
    days_ago=1,
    salary_min=None,
    salary_max=None,
):
    """Build a job that passes the scorer but FAILS the strict title gate.

    The title is a weak industrial-trades token (``Soldador``) with no growth
    keyword, so the digest gate rejects it; the description carries ``calidad``
    so the scorer accepts it via the quality group. This is the canonical
    fallback candidate: a real nearby option whose role signal lives in the
    description, not the headline. Defaults score 120 (Silao tier 50 + quality
    group 70); override ``raw_location`` to vary the score by tier.
    """
    job = make_job(
        job_id,
        title=title,
        raw_location=raw_location,
        description=description,
        days_ago=days_ago,
        salary_min=salary_min,
        salary_max=salary_max,
    )
    job.career = title
    return job


class TestFallbackSection:
    """The secondary ``fallback_jobs`` tier: lower-confidence recommendations.

    The strict title gate stays authoritative for the PRIMARY list. A
    scorer-accepted job the gate rejects (role signal in the description, not
    the title) becomes a fallback candidate, ranked by the same score/date/id
    key, capped at ``fallback_limit`` (default 5), and never overlapping the
    primary list. Scorer-rejected and column-rule-failing jobs are NOT fallback
    candidates -- there is no fit signal at all.
    """

    def test_gate_rejected_scorer_accepted_job_goes_to_fallback(self):
        """A Soldador job (scorer-accepted, gate-rejected) surfaces in the
        secondary tier, NOT the primary headline."""
        job = make_fallback_job(1)
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        assert payload.count == 0
        assert _ids(payload) == []
        assert _fallback_ids(payload) == [1]

    def test_strict_gate_passing_job_goes_to_primary_not_fallback(self):
        """A SAP WM job (gate-passing) is primary only and never leaks into the
        fallback tier."""
        job = make_job(1, title="SAP WM Analyst", raw_location="Silao, Guanajuato")
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        assert _ids(payload) == [1]
        assert _fallback_ids(payload) == []

    def test_primary_and_fallback_split_in_one_call(self):
        """One strict job + one fallback job: each lands in its own tier."""
        strict = make_job(1, title="SAP WM Analyst", raw_location="Silao, Guanajuato")
        fallback = make_fallback_job(2)
        payload = select_digest(
            [strict, fallback], NOW, profile=PROFILE, limit=10
        )

        assert _ids(payload) == [1]
        assert _fallback_ids(payload) == [2]
        # The two tiers never share a job id.
        assert set(_ids(payload)).isdisjoint(_fallback_ids(payload))

    def test_fallback_excludes_primary_jobs_defensively(self):
        """Even when the same id appears in both candidate streams, a job
        selected for primary must never also appear in fallback. The gate is
        mutually exclusive, so this is a defensive guarantee against
        duplicate-id input rows."""
        # A gate-passing job with id=1 ...
        strict = make_job(1, title="SAP WM Analyst", raw_location="Silao, Guanajuato")
        # ... and a gate-rejected fallback job with the SAME id (duplicate row).
        fallback_dup = make_fallback_job(1)
        payload = select_digest(
            [strict, fallback_dup], NOW, profile=PROFILE, limit=10
        )

        assert _ids(payload) == [1]
        # The duplicate-id fallback row is excluded because id 1 is primary.
        assert _fallback_ids(payload) == []

    def test_fallback_capped_at_fallback_limit(self):
        """Seven fallback candidates with fallback_limit=5 -> only the five
        highest-ranked surface; the rest are dropped (not overflowed into
        primary)."""
        # All score 120 (Silao + quality), same date -> id ascending breaks the
        # tie, so the first five ids surface.
        jobs = [make_fallback_job(i) for i in range(1, 8)]
        payload = select_digest(
            jobs, NOW, profile=PROFILE, limit=10, fallback_limit=5
        )

        assert _fallback_ids(payload) == [1, 2, 3, 4, 5]
        assert len(payload.fallback_jobs) == 5

    def test_primary_overflow_does_not_become_fallback(self):
        """Gate-PASSING jobs beyond the primary cap are NOT fallback. Fallback
        is for gate-REJECTED scorer-accepted jobs only, so 12 strict jobs with
        limit=10 yield 10 primary and ZERO fallback (the 2 overflow strict jobs
        are dropped, not demoted)."""
        jobs = [
            make_job(i, title="SAP WM Analyst", raw_location="Silao, Guanajuato")
            for i in range(1, 13)
        ]
        payload = select_digest(jobs, NOW, profile=PROFILE, limit=10)

        assert payload.count == 10
        assert _ids(payload) == list(range(1, 11))
        assert _fallback_ids(payload) == []

    def test_fallback_limit_zero_disables_section(self):
        """fallback_limit=0 yields an empty secondary tier even when fallback
        candidates exist, so a caller can opt out of the section cleanly."""
        job = make_fallback_job(1)
        payload = select_digest(
            [job], NOW, profile=PROFILE, limit=10, fallback_limit=0
        )

        assert _fallback_ids(payload) == []
        assert payload.fallback_jobs == ()

    def test_negative_fallback_limit_clamped_to_zero(self):
        """A negative fallback_limit must NOT wrap to tail elements (the same
        slice footgun guarded for the primary limit)."""
        job = make_fallback_job(1)
        payload = select_digest(
            [job], NOW, profile=PROFILE, limit=10, fallback_limit=-1
        )

        assert _fallback_ids(payload) == []

    def test_default_fallback_limit_constant_is_five(self):
        # Product contract: the secondary section cap defaults to 5 so the total
        # email (10 primary + 5 fallback) stays scannable. Asserted at the
        # constant level so an accidental config change is caught here.
        assert DIGEST_DEFAULT_FALLBACK_LIMIT == 5

    def test_fallback_ranked_by_score_descending(self):
        """Fallback uses the SAME ranking key as primary: score desc, then
        date_scraped desc, then id asc. Three fallback jobs with distinct
        scores (Silao 120, Salamanca 100, Irapuato 90) surface in score order
        regardless of input order."""
        high = make_fallback_job(10, raw_location="Silao, Guanajuato")  # 120
        mid = make_fallback_job(11, raw_location="Salamanca, Guanajuato")  # 100
        low = make_fallback_job(12, raw_location="Irapuato, Guanajuato")  # 90
        payload = select_digest(
            [low, high, mid], NOW, profile=PROFILE, limit=10
        )

        assert _fallback_ids(payload) == [10, 11, 12]

    def test_fallback_date_scraped_descending_breaks_score_tie(self):
        """Equal-score fallback jobs rank newer-first, mirroring primary."""
        newer = make_fallback_job(1, days_ago=1)
        older = make_fallback_job(2, days_ago=2)
        payload = select_digest(
            [older, newer], NOW, profile=PROFILE, limit=10
        )

        assert _fallback_ids(payload) == [1, 2]

    def test_fallback_id_ascending_is_final_tiebreaker(self):
        """Equal score AND date -> id ascending, deterministic across runs."""
        same_date = NOW - timedelta(days=1)
        a = make_fallback_job(2, days_ago=1)
        b = make_fallback_job(1, days_ago=1)
        a.date_scraped = same_date
        b.date_scraped = same_date
        payload = select_digest([a, b], NOW, profile=PROFILE, limit=10)

        assert _fallback_ids(payload) == [1, 2]

    def test_fallback_excludes_scorer_rejected_jobs(self):
        """A wrong-geography job the scorer rejects is NOT a fallback candidate:
        there is no fit signal at all, so it appears in neither tier."""
        wrong_geo = make_job(
            1, title="Soldador", raw_location="Queretaro, Queretaro",
            description="Soldadura con calidad en planta.",
        )
        wrong_geo.career = "Soldador"
        payload = select_digest([wrong_geo], NOW, profile=PROFILE, limit=10)

        assert payload.count == 0
        assert _fallback_ids(payload) == []

    def test_fallback_excludes_column_rule_failures(self):
        """A stale or wrong-niche job never reaches the scorer, so it cannot be
        a fallback candidate either."""
        stale = make_fallback_job(1, days_ago=30)
        wrong_niche = make_fallback_job(2)
        wrong_niche.industry_niche = "Tech"
        payload = select_digest(
            [stale, wrong_niche], NOW, profile=PROFILE, freshness_days=5, limit=10
        )

        assert _fallback_ids(payload) == []

    def test_payload_count_is_primary_only(self):
        """``count`` reports the PRIMARY count only; the fallback tier is
        reported via ``fallback_jobs`` so callers distinguish the two confidence
        tiers without ambiguity."""
        strict = make_job(1, title="SAP WM Analyst", raw_location="Silao, Guanajuato")
        strict2 = make_job(2, title="SAP WM", raw_location="Silao, Guanajuato")
        fb = make_fallback_job(3)
        fb2 = make_fallback_job(4, raw_location="Salamanca, Guanajuato")
        fb3 = make_fallback_job(5, raw_location="Irapuato, Guanajuato")
        payload = select_digest(
            [strict, strict2, fb, fb2, fb3], NOW, profile=PROFILE, limit=10
        )

        assert payload.count == 2
        assert len(payload.fallback_jobs) == 3

    def test_fallback_jobs_are_digest_job_instances(self):
        """Fallback rows are full :class:`DigestJob` instances, not raw jobs, so
        the renderer can treat both tiers uniformly."""
        job = make_fallback_job(1)
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        assert len(payload.fallback_jobs) == 1
        assert isinstance(payload.fallback_jobs[0], DigestJob)
        assert payload.fallback_jobs[0].id == 1

    def test_fallback_payload_is_json_serializable(self):
        """The fallback tier must survive asdict + json.dumps (the sender
        contract), like the primary tier."""
        job = make_fallback_job(1, salary_min=Decimal("20000.00"))
        payload = select_digest([job], NOW, profile=PROFILE, limit=10)

        data = payload_to_dict(payload)
        serialized = json.dumps(data)
        parsed = json.loads(serialized)
        assert parsed["fallback_jobs"][0]["id"] == 1
        assert parsed["fallback_jobs"][0]["salary_min"] == 20000.0


class TestLowPriorityTradeKeywords:
    """Unit tests for the weak-trade-keyword derivation that backs the gate."""

    def test_returns_trades_keywords_for_default_profile(self):
        """The weak set is exactly the industrial-trades group keywords."""
        weak = _low_priority_trade_keywords(INDUSTRIAL_IRAPUATO_BAJIO_ROLE_GROUPS)

        # Representative trades tokens are weak; an accidental profile edit that
        # moves them out of the trades bucket is caught here.
        assert "mantenimiento" in weak
        assert "electricista" in weak
        assert "soldador" in weak
        assert "tecnico" in weak
        # Growth-role keywords are NOT weak.
        assert "sap" not in weak
        assert "calidad" not in weak
        assert "almacenista" not in weak
        assert "operador" not in weak

    def test_empty_role_groups_returns_empty_set(self):
        assert _low_priority_trade_keywords(()) == frozenset()

    def test_falls_back_to_min_weight_when_named_group_absent(self):
        """When no group matches the digest constant name, the minimum-weight
        group is used as the weak set so the gate still excludes the
        lowest-priority bucket."""
        groups = (
            RoleGroup(name="growth", keywords=("sap", "calidad"), weight=100),
            RoleGroup(name="other trades", keywords=("weld",), weight=10),
        )
        weak = _low_priority_trade_keywords(groups)

        assert weak == frozenset({"weld"})


def _to_record(job):
    """Mirror the selector's internal Job -> score_job record bridge."""
    return {
        "title": job.title,
        "raw_location": job.raw_location,
        "description": job.description,
    }


def aware_utc_check(dt):
    """Local mirror of shared.utils.aware_utc for round-trip assertions."""
    if dt is None:
        return datetime.fromtimestamp(0, tz=_UTC)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_UTC)
    return dt.astimezone(_UTC)
