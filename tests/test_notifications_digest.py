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
    DIGEST_DEFAULT_LIMIT,
    DigestJob,
    DigestPayload,
    payload_to_dict,
    select_digest,
)
from notifications.profiles import INDUSTRIAL_IRAPUATO_BAJIO_PROFILE
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
            2, title="Operador de Produccion", raw_location="Irapuato, Guanajuato"
        )  # 60
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
          C id=3 Operador @ Irap score 60,  scraped 1d ago
        Expected: A, B, C.
        """
        a = make_job(1, title="SAP WM Analyst", raw_location="Silao, Guanajuato", days_ago=1)
        b = make_job(2, title="SAP WM Specialist", raw_location="Silao, Guanajuato", days_ago=2)
        c = make_job(
            3, title="Operador de Produccion", raw_location="Irapuato, Guanajuato", days_ago=1
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
            2, title="Operador de Produccion", raw_location="Irapuato, Guanajuato"
        )
        future_low.date_scraped = NOW + timedelta(days=365)
        legit_high = make_job(
            1, title="SAP WM Analyst", raw_location="Silao, Guanajuato", days_ago=1
        )
        payload = select_digest([future_low, legit_high], NOW, profile=PROFILE, limit=10)

        # Score still wins: 150 > 60 regardless of the clamped timestamp.
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

    def test_no_eligible_jobs_returns_empty_payload(self):
        jobs = [
            make_job(1, industry_niche="Tech"),
            make_job(2, status="NOTIFIED"),
            make_job(3, description=""),
        ]
        payload = select_digest(jobs, NOW, profile=PROFILE, limit=10)

        assert payload.count == 0
        assert payload.jobs == ()


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
# Sanity: score_job verdict matches the selector's include decision
# ---------------------------------------------------------------------------


class TestScoringParity:
    def test_selected_jobs_are_exactly_those_score_job_accepts(self):
        """The selector's fit gate is score_job; every selected job must be one
        score_job accepts, and every rejected eligible-column job must be one
        score_job rejects. Guards against the selector diverging from the
        scorer's contract."""
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
