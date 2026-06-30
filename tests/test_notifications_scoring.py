"""Tests for notifications.scoring: CV-informed, deterministic ranking.

Covers the industrial Bajío candidate profile (brother's CV): role-group
priorities (SAP/inventory highest, quality strong, operator lower), location
tiers (Silao/Puerto Interior tier 1 above Irapuato tier 3), hard rejects
(internships and unpaid terms), geography rejection (Querétaro), stable
ordering of score_jobs, and backward parity with the binary matcher
(``matched_city``/``matched_keyword`` still present).
"""

from notifications.profiles import (
    AlertProfile,
    INDUSTRIAL_IRAPUATO_BAJIO_PROFILE,
    LocationTier,
    RoleGroup,
)
from notifications.scoring import score_job, score_jobs

PROFILE = INDUSTRIAL_IRAPUATO_BAJIO_PROFILE


def _job(title: str, location: str, description: str = "", **extra) -> dict:
    """Build a transform-shaped job record with optional extra fields."""
    record = {
        "title": title,
        "raw_location": location,
        "description": description,
        "job_url": "https://example.com/job/1",
        "company": "Industrias Bajío",
    }
    record.update(extra)
    return record


# ---------------------------------------------------------------------------
# Role priority: SAP/inventory/materials outranks generic operator
# ---------------------------------------------------------------------------


class TestRolePriority:
    def test_sap_wm_in_silao_scores_top_of_scale(self):
        result = score_job(
            _job("SAP WM Analyst", "Silao, Guanajuato",
                 description="Gestión de warehouse management con SAP."),
            PROFILE,
        )
        assert result is not None
        # Tier 1 (Silao, 50) + highest role group (100) = top score 150.
        assert result["score"] == 150
        assert "SAP / inventory" in result["matched_role_group"]
        assert result["location_tier"] == "Silao / Puerto Interior"

    def test_generic_operator_in_irapuato_scores_lower_than_sap_in_silao(self):
        sap = score_job(_job("SAP WM Analyst", "Silao, Guanajuato"), PROFILE)
        operator = score_job(
            _job("Operador de Producción", "Irapuato, Guanajuato"), PROFILE
        )
        assert sap is not None and operator is not None
        # Operator -> role group 40 + Irapuato tier 3 (20) = 60.
        assert operator["score"] == 60
        assert sap["score"] > operator["score"]

    def test_inventory_control_in_salamanca_scores_high(self):
        result = score_job(
            _job("Analista de Control de Inventarios", "Salamanca, Guanajuato",
                 description="Validación de stock y trazabilidad."),
            PROFILE,
        )
        assert result is not None
        # Highest role group (100) + Salamanca tier 2 (30) = 130.
        assert result["score"] == 130
        assert "SAP / inventory" in result["matched_role_group"]

    def test_materials_analyst_in_celaya_scores_high(self):
        result = score_job(
            _job("Analista de Materiales", "Celaya, Guanajuato"), PROFILE
        )
        assert result is not None
        assert result["score"] == 130
        assert "SAP / inventory" in result["matched_role_group"]

    def test_quality_role_in_celaya_scores_strong(self):
        result = score_job(
            _job("Quality Analyst", "Celaya, Guanajuato",
                 description="Control de calidad en línea de producción."),
            PROFILE,
        )
        assert result is not None
        # Quality role group (70) + Celaya tier 2 (30) = 100.
        assert result["score"] == 100
        assert "quality" in result["matched_role_group"]

    def test_warehouse_assistant_not_promoted_to_highest_group(self):
        # "almacenista" must fall into the operator/support group (40), not the
        # highest group's "almacen"-style keywords.
        result = score_job(
            _job("Almacenista", "Irapuato, Guanajuato"), PROFILE
        )
        assert result is not None
        assert "operator / warehouse support" in result["matched_role_group"]
        assert result["matched_role_weight"] == 40

    def test_first_match_wins_gives_most_favorable_group(self):
        # Title contains "sap" (highest, 100) and description "operador" (lower,
        # 40). Highest must win because groups are checked highest first.
        result = score_job(
            _job("SAP WM Analyst", "Silao, Guanajuato",
                 description="Se requiere operador de montacargas."),
            PROFILE,
        )
        assert result is not None
        assert result["matched_role_weight"] == 100


# ---------------------------------------------------------------------------
# Location tiers: Silao/Puerto Interior above Irapuato
# ---------------------------------------------------------------------------


class TestLocationTiers:
    def test_puerto_interior_is_tier_1(self):
        # Puerto Interior is an industrial park in Silao and a Tier-1 token.
        result = score_job(
            _job("Analista de Logística", "Puerto Interior, Silao, Guanajuato"),
            PROFILE,
        )
        assert result is not None
        assert result["matched_city"] == "puerto interior"
        assert result["location_tier"] == "Silao / Puerto Interior"
        assert result["location_weight"] == 50

    def test_irapuato_is_tier_3_not_highest(self):
        result = score_job(
            _job("Analista de Logística", "Irapuato, Guanajuato"), PROFILE
        )
        assert result is not None
        assert result["location_tier"] == "Irapuato / León"
        assert result["location_weight"] == 20

    def test_same_role_ranks_silao_above_irapuato(self):
        silao = score_job(
            _job("Analista de Logística", "Silao, Guanajuato"), PROFILE
        )
        irapuato = score_job(
            _job("Analista de Logística", "Irapuato, Guanajuato"), PROFILE
        )
        assert silao is not None and irapuato is not None
        assert silao["score"] > irapuato["score"]

    def test_queretaro_rejected_by_geography(self):
        result = score_job(
            _job("SAP WM Analyst", "Querétaro, Qro."), PROFILE
        )
        assert result is None


# ---------------------------------------------------------------------------
# Hard rejects: internships and unpaid terms, even with strong role keywords
# ---------------------------------------------------------------------------


class TestHardRejects:
    def test_becario_sap_rejected(self):
        result = score_job(
            _job("Becario SAP WM", "Silao, Guanajuato"), PROFILE
        )
        assert result is None

    def test_pasante_quality_rejected(self):
        result = score_job(
            _job("Pasante de Calidad", "Celaya, Guanajuato"), PROFILE
        )
        assert result is None

    def test_practicante_logistica_rejected(self):
        result = score_job(
            _job("Practicante de Logística", "León, Guanajuato"), PROFILE
        )
        assert result is None

    def test_unpaid_volunteer_rejected_via_reject_keywords(self):
        # "voluntario" is in reject_keywords, not in exclude_keywords; the scorer
        # must still reject it.
        result = score_job(
            _job("Quality Analyst", "Celaya, Guanajuato",
                 description="Posición voluntario sin remuneracion."),
            PROFILE,
        )
        assert result is None


# ---------------------------------------------------------------------------
# score_jobs: ranking, cap, stability
# ---------------------------------------------------------------------------


class TestScoreJobs:
    def test_ranks_by_score_descending(self):
        records = [
            _job("Operador de Producción", "Irapuato, Guanajuato"),   # 60
            _job("SAP WM Analyst", "Silao, Guanajuato"),                # 150
            _job("Quality Analyst", "Celaya, Guanajuato"),             # 100
        ]
        results = score_jobs(records, PROFILE)
        assert [r["score"] for r in results] == [150, 100, 60]
        assert results[0]["matched_city"] == "silao"
        assert results[1]["matched_city"] == "celaya"
        assert results[2]["matched_city"] == "irapuato"

    def test_ties_preserve_input_order(self):
        # Two SAP jobs in Silao tie at 150; input order must be preserved.
        records = [
            _job("SAP WM Analyst", "Silao, Guanajuato", job_url="a"),
            _job("Inventory Analyst", "Silao, Guanajuato", job_url="b"),
        ]
        results = score_jobs(records, PROFILE)
        assert results[0]["job_url"] == "a"
        assert results[1]["job_url"] == "b"
        assert results[0]["score"] == results[1]["score"]

    def test_caps_at_max_jobs(self):
        capped = AlertProfile(
            name="capped",
            email="",
            allowed_cities=PROFILE.allowed_cities,
            include_keywords=PROFILE.include_keywords,
            exclude_keywords=PROFILE.exclude_keywords,
            role_groups=PROFILE.role_groups,
            location_tiers=PROFILE.location_tiers,
            reject_keywords=PROFILE.reject_keywords,
            max_jobs=2,
        )
        records = [
            _job("Operador de Producción", "Irapuato, Guanajuato"),
            _job("SAP WM Analyst", "Silao, Guanajuato"),
            _job("Quality Analyst", "Celaya, Guanajuato"),
        ]
        results = score_jobs(records, capped)
        assert len(results) == 2
        assert results[0]["score"] == 150

    def test_empty_input_returns_empty(self):
        assert score_jobs([], PROFILE) == []

    def test_all_rejected_returns_empty(self):
        records = [
            _job("Becario SAP WM", "Silao, Guanajuato"),
            _job("SAP WM Analyst", "Querétaro, Qro."),
        ]
        assert score_jobs(records, PROFILE) == []


# ---------------------------------------------------------------------------
# Backward parity with the binary matcher + explainability
# ---------------------------------------------------------------------------


class TestParityAndExplanations:
    def test_digest_keeps_binary_matcher_fields(self):
        result = score_job(
            _job("Operador de Producción", "Irapuato, Guanajuato",
                 company="Aceros Bajío"),
            PROFILE,
        )
        assert result is not None
        # Binary matcher fields are still present (parity for future renderer).
        assert result["matched_city"] == "irapuato"
        assert result["matched_keyword"] == "operador"
        # Original fields preserved.
        assert result["company"] == "Aceros Bajío"
        assert result["job_url"] == "https://example.com/job/1"

    def test_does_not_mutate_input(self):
        record = _job("SAP WM Analyst", "Silao, Guanajuato")
        result = score_job(record, PROFILE)
        assert result is not None
        assert "score" not in record
        assert "matched_city" not in record
        assert result is not record

    def test_match_reasons_are_human_readable(self):
        result = score_job(
            _job("SAP WM Analyst", "Silao, Guanajuato"), PROFILE
        )
        assert result is not None
        reasons = result["match_reasons"]
        assert any("Location:" in r and "Silao" in r for r in reasons)
        assert any("Role:" in r and "SAP" in r for r in reasons)


# ---------------------------------------------------------------------------
# Empty scoring config: a profile without tiers/groups still filters cleanly
# ---------------------------------------------------------------------------


class TestEmptyScoringConfig:
    def test_profile_without_tiers_scores_zero_but_still_matches(self):
        minimal = AlertProfile(
            name="minimal",
            email="",
            allowed_cities=PROFILE.allowed_cities,
            include_keywords=PROFILE.include_keywords,
            exclude_keywords=PROFILE.exclude_keywords,
        )
        result = score_job(
            _job("Operador de Producción", "Irapuato, Guanajuato"), minimal
        )
        assert result is not None
        assert result["score"] == 0
        assert result["location_tier"] == ""
        assert result["matched_role_group"] == ""
        assert result["matched_keyword"] == "operador"

    def test_role_group_keyword_specificity(self):
        # Sanity: RoleGroup/LocationTier are frozen and orderable.
        g = RoleGroup(name="g", keywords=("x",), weight=10)
        t = LocationTier(name="t", cities=("x",), weight=5)
        assert g.weight == 10
        assert t.cities == ("x",)


# ---------------------------------------------------------------------------
# Data-driven matcher/scorer parity over EVERY role-group keyword.
# Product contract: scoring ranks alert-matched candidates, so for any
# industrial role-group keyword that score_job accepts, match_job must accept
# too. Constructing a record whose title IS the keyword (an allowed location
# like Silao) and asserting ``score_job accept => match_job accept`` keeps the
# contract honest as role-group vocabulary evolves. Boundary semantics
# (e.g. "sap", "quality", "lean" require word boundaries) are exercised
# naturally because the title is the keyword by itself.
# ---------------------------------------------------------------------------


import pytest  # noqa: E402


def _all_role_group_keywords() -> list[tuple[str, str]]:
    """Return ``(group_name, keyword)`` pairs for every industrial role keyword."""
    pairs: list[tuple[str, str]] = []
    for group in PROFILE.role_groups:
        for keyword in group.keywords:
            pairs.append((group.name, keyword))
    return pairs


class TestRoleGroupKeywordParity:
    @pytest.mark.parametrize(
        "group_name, keyword",
        _all_role_group_keywords(),
        ids=lambda v: v if isinstance(v, int) else "",
    )
    def test_score_accept_implies_match_accept(self, group_name, keyword):
        # Build a record whose title is exactly the role-group keyword in an
        # allowed Tier-1 city. If the scorer accepts (most do, since the title
        # hits the role group), the matcher must accept too.
        record = _job(keyword, "Silao, Guanajuato")
        scored = score_job(record, PROFILE)
        matched = match_job(record, PROFILE)
        if scored is not None:
            assert matched is not None, (
                f"contract violation: role-group keyword {keyword!r} in group "
                f"{group_name!r} was accepted by score_job (score="
                f"{scored['score']}) but rejected by match_job"
            )

    def test_montacarguista_in_silao_accepted_by_both(self):
        # Explicit regression for the reported blocker: "Montacarguista" in
        # Silao previously scored but was rejected by match_job because
        # "montacarguista" lived only in the operator role group, not in the
        # profile's include_keywords.
        record = _job("Montacarguista", "Silao, Guanajuato")
        assert match_job(record, PROFILE) is not None
        scored = score_job(record, PROFILE)
        assert scored is not None
        # Tier 1 (50) + operator/warehouse-support group (40) = 90.
        assert scored["score"] == 90
        assert "operator / warehouse support" in scored["matched_role_group"]

    def test_every_role_group_keyword_is_in_include_keywords(self):
        # Static guarantee: no role-group keyword is hidden only in scoring.
        # Future edits to role_groups that add a keyword without mirroring it
        # into include_keywords will trip this test, surfacing the drift early
        # rather than via a parity failure in a future review.
        include = set(PROFILE.include_keywords)
        for group in PROFILE.role_groups:
            missing = [k for k in group.keywords if k not in include]
            assert not missing, (
                f"role group {group.name!r} has keywords not in "
                f"include_keywords: {missing}"
            )


# ---------------------------------------------------------------------------
# Boundary regression for "lean" (added to _EXACT_MATCH_KEYWORDS this slice).
# "lean" leaks inside "cleans", "cleanliness", "leaning", "lineamiento".
# ---------------------------------------------------------------------------


class TestLeanBoundaryRegression:
    def test_lean_inside_cleans_does_not_match_keyword(self):
        assert _keyword_in_text("lean", "cleans the warehouse") is False

    def test_lean_inside_cleanliness_does_not_match_keyword(self):
        assert _keyword_in_text("lean", "cleanliness standards") is False

    def test_lean_inside_lineamiento_does_not_match_keyword(self):
        # "lineamiento" is a Spanish policy-guideline noun; bare "lean"
        # substring-matches it but a Lean manufacturing role does not.
        assert _keyword_in_text("lean", "lineamiento operativo") is False

    def test_lean_standalone_matches(self):
        assert _keyword_in_text("lean", "manufactura lean") is True

    def test_lean_role_in_allowed_city_accepted_by_both(self):
        # "Mejora Continua Lean" -> description has "lean"; matches include too.
        record = _job("Coordinador de Mejora Continua", "Silao, Guanajuato",
                       description="Experiencia en manufactura lean.")
        assert match_job(record, PROFILE) is not None
        assert score_job(record, PROFILE) is not None


# ---------------------------------------------------------------------------
# Boundary semantics for short exact keywords. Regression for the blocker
# where "WhatsApp" and "Sapphire" false-positive matched the bare "sap"
# include/role-group keyword. Exact tokens (sap, quality) require word
# boundaries; longer Spanish terms (almacen -> almacenista) stay substring.
# ---------------------------------------------------------------------------


from notifications.matcher import _keyword_in_text  # noqa: E402


class TestBoundarySemantics:
    def test_sap_inside_whatsapp_does_not_match_keyword(self):
        # The demonstrated blocker: "WhatsApp" contains "sap" as a substring.
        assert _keyword_in_text("sap", "enviar cv por whatsapp") is False

    def test_sap_inside_sapphire_does_not_match_keyword(self):
        assert _keyword_in_text("sap", "sapphire specialist") is False

    def test_sap_standalone_matches(self):
        assert _keyword_in_text("sap", "experiencia con sap") is True

    def test_sap_with_hyphenated_suffix_matches(self):
        # "SAP-WM" normalized -> "sap-wm"; boundary after "p" hits the hyphen.
        assert _keyword_in_text("sap", "sap-wm analyst") is True

    def test_sap_with_trailing_punctuation_matches(self):
        # "Gestión SAP." normalized -> "gestion sap."; boundary after "p" hits ".".
        assert _keyword_in_text("sap", "gestion sap.") is True

    def test_quality_inside_equality_does_not_match_keyword(self):
        assert _keyword_in_text("quality", "equality officer") is False

    def test_quality_standalone_matches(self):
        assert _keyword_in_text("quality", "quality analyst") is True

    def test_almacen_substring_still_matches_almacenista(self):
        # Longer Spanish terms keep substring semantics: "almacen" must still
        # match "almacenista", which is a legitimate adjacent role.
        assert _keyword_in_text("almacen", "almacenista") is True

    def test_recepcionista_with_whatsapp_rejected_by_both(self):
        # End-to-end regression: the exact blocker record from the review.
        record = _job("Recepcionista", "Silao, Guanajuato",
                      description="Enviar CV por WhatsApp")
        assert match_job(record, PROFILE) is None
        assert score_job(record, PROFILE) is None

    def test_sapphire_role_in_allowed_city_rejected_by_both(self):
        record = _job("Sapphire Specialist", "Silao, Guanajuato")
        assert match_job(record, PROFILE) is None
        assert score_job(record, PROFILE) is None

    def test_equality_role_in_allowed_city_rejected_by_both(self):
        record = _job("Equality Officer", "Celaya, Guanajuato")
        assert match_job(record, PROFILE) is None
        assert score_job(record, PROFILE) is None

    def test_sap_wm_analyst_still_accepted_and_scored_top(self):
        record = _job("SAP WM Analyst", "Silao, Guanajuato")
        assert match_job(record, PROFILE) is not None
        result = score_job(record, PROFILE)
        assert result is not None
        assert result["score"] == 150

    def test_sap_hyphen_wm_variant_still_accepted(self):
        record = _job("SAP-WM Analyst", "Silao, Guanajuato")
        assert match_job(record, PROFILE) is not None
        assert score_job(record, PROFILE) is not None

    def test_sap_trailing_punctuation_variant_still_accepted(self):
        record = _job("Operations with SAP.", "Silao, Guanajuato")
        assert match_job(record, PROFILE) is not None
        assert score_job(record, PROFILE) is not None


# ---------------------------------------------------------------------------
# Matcher reject_keywords contract: unpaid/volunteer terms are part of the
# global alert relevance gate, rejected by match_job too (not only scorer).
# ---------------------------------------------------------------------------


class TestMatcherRejectKeywords:
    def test_match_job_rejects_unpaid_via_reject_keywords(self):
        # "sin remuneracion" is in reject_keywords, not exclude_keywords; the
        # matcher must still reject it now that match_job unions both.
        record = _job("Quality Analyst", "Celaya, Guanajuato",
                      description="Posición sin remuneracion inicial.")
        assert match_job(record, PROFILE) is None
        assert score_job(record, PROFILE) is None

    def test_match_job_rejects_volunteer_via_reject_keywords(self):
        record = _job("Quality Analyst", "Celaya, Guanajuato",
                      description="Voluntario en control de calidad.")
        assert match_job(record, PROFILE) is None
        assert score_job(record, PROFILE) is None

    def test_legacy_profile_without_reject_keywords_still_works(self):
        # Backward compatibility: a profile with no reject_keywords behaves
        # exactly as before (reject set = exclude_keywords only).
        legacy = AlertProfile(
            name="legacy",
            email="",
            allowed_cities=("irapuato",),
            include_keywords=("calidad",),  # substring-ish, long enough to skip exact
            exclude_keywords=("becario",),
        )
        legitimate = _job("Tecnico de Calidad", "Irapuato, Guanajuato")
        rejected = _job("Becario de Calidad", "Irapuato, Guanajuato")
        assert match_job(legitimate, legacy) is not None
        assert match_job(rejected, legacy) is None
        # A volunteer posting is ACCEPTED by the legacy profile (no reject
        # vocabulary), proving the union only broadens rejection when the
        # profile actually defines reject_keywords.
        volunteer = _job("Tecnico de Calidad", "Irapuato, Guanajuato",
                         description="Voluntario en planta.")
        assert match_job(volunteer, legacy) is not None


# ---------------------------------------------------------------------------
# Scoring/matcher contract parity: scoring ranks alert-matched candidates.
# High-value CV terms live in the profile's relevance vocabulary
# (include_keywords), so any job score_job accepts must also be accepted by
# match_job. The scorer never widens the candidate set beyond the matcher.
# ---------------------------------------------------------------------------


from notifications.matcher import match_job  # noqa: E402


class TestScoringMatcherContract:
    def test_match_job_accepts_sap_wm_analyst_in_silao(self):
        record = _job("SAP WM Analyst", "Silao, Guanajuato",
                      description="Gestión de warehouse management con SAP.")
        assert match_job(record, PROFILE) is not None

    def test_match_job_accepts_warehouse_operations_in_allowed_geography(self):
        record = _job("Warehouse Operations Analyst", "Silao, Guanajuato")
        assert match_job(record, PROFILE) is not None

    def test_match_job_accepts_inventory_control_in_allowed_geography(self):
        record = _job("Inventory Control Analyst", "Celaya, Guanajuato")
        assert match_job(record, PROFILE) is not None

    def test_match_job_accepts_materials_analyst_in_allowed_geography(self):
        record = _job("Analista de Materiales", "Celaya, Guanajuato")
        assert match_job(record, PROFILE) is not None

    def test_match_job_accepts_quality_analyst_in_allowed_geography(self):
        record = _job("Quality Analyst", "Celaya, Guanajuato")
        assert match_job(record, PROFILE) is not None

    @staticmethod
    def _representative_high_value_roles() -> list[dict]:
        """Representative high-value CV roles across geographies and groups."""
        return [
            _job("SAP WM Analyst", "Silao, Guanajuato"),
            _job("Warehouse Operations Analyst", "Silao, Guanajuato"),
            _job("Inventory Control Analyst", "Celaya, Guanajuato"),
            _job("Analista de Materiales", "Salamanca, Guanajuato"),
            _job("Analista de Logística", "León, Guanajuato"),
            _job("Quality Analyst", "Celaya, Guanajuato"),
            _job("Production Planning Analyst", "Irapuato, Guanajuato"),
            _job("Continuous Improvement Analyst", "Silao, Guanajuato"),
            _job("Operador de Producción", "Irapuato, Guanajuato"),
            _job("Soldador", "Salamanca, Guanajuato"),
        ]

    def test_score_job_accept_implies_match_job_accept(self):
        # Core contract: every job score_job accepts, match_job must also accept.
        for record in self._representative_high_value_roles():
            scored = score_job(record, PROFILE)
            assert scored is not None, (
                f"score_job unexpectedly rejected: {record['title']!r}"
            )
            matched = match_job(record, PROFILE)
            assert matched is not None, (
                f"contract violation: score_job accepted but match_job rejected "
                f"{record['title']!r} in {record['raw_location']!r}"
            )

    def test_recepcionista_rejected_by_both_matcher_and_scorer(self):
        record = _job("Recepcionista", "Silao, Guanajuato")
        assert match_job(record, PROFILE) is None
        assert score_job(record, PROFILE) is None

    def test_queretaro_rejected_by_both_matcher_and_scorer(self):
        record = _job("SAP WM Analyst", "Querétaro, Qro.")
        assert match_job(record, PROFILE) is None
        assert score_job(record, PROFILE) is None

    def test_internship_rejected_by_both_matcher_and_scorer(self):
        record = _job("Becario SAP WM", "Silao, Guanajuato")
        assert match_job(record, PROFILE) is None
        assert score_job(record, PROFILE) is None


# ---------------------------------------------------------------------------
# Relevance parity: an allowed city alone never widens the candidate set.
# The scorer must preserve the binary matcher's relevance semantics: a job with
# no include keyword AND no role-group hit is rejected, not silently scored.
# Regression for the "Recepcionista in Silao" blocker.
# ---------------------------------------------------------------------------


class TestRelevanceParity:
    def test_irrelevant_role_in_allowed_city_rejected(self):
        # "Recepcionista" is in Silao (allowed, Tier 1) but has no include
        # keyword and no role-group hit. The binary matcher rejects it; the
        # scorer must too, not award it the Tier-1 weight of 50.
        result = score_job(_job("Recepcionista", "Silao, Guanajuato"), PROFILE)
        assert result is None

    def test_missing_title_and_description_rejected(self):
        # No searchable text at all: no include keyword, no role-group hit.
        result = score_job({"raw_location": "Silao, Guanajuato"}, PROFILE)
        assert result is None

    def test_empty_title_and_description_rejected(self):
        record = {
            "title": "",
            "raw_location": "Silao, Guanajuato",
            "description": "",
        }
        assert score_job(record, PROFILE) is None

    def test_allowed_city_role_signal_only_in_description_still_scores(self):
        # Title is irrelevant, but the description carries an include keyword
        # and role-group hit: relevance is satisfied via the description.
        result = score_job(
            _job("Personal de Planta", "Irapuato, Guanajuato",
                 description="Buscamos analista de inventarios con SAP."),
            PROFILE,
        )
        assert result is not None
        assert "SAP / inventory" in result["matched_role_group"]

    def test_role_group_fallback_when_group_keyword_absent_from_include(self):
        # The scorer keeps a role-group fallback branch for safety: when a
        # profile defines role_groups with a keyword NOT duplicated in
        # include_keywords, a role-group hit alone is still a sufficient
        # relevance signal. This synthetic profile isolates that fallback path
        # from the industrial profile, where every high-value CV term is now
        # also a relevance keyword.
        synthetic = AlertProfile(
            name="synthetic",
            email="",
            allowed_cities=("irapuato",),
            include_keywords=("operador",),  # does NOT contain "quirkrole"
            exclude_keywords=(),
            role_groups=(
                RoleGroup(name="quirk", keywords=("quirkrole",), weight=25),
            ),
            location_tiers=(
                LocationTier(name="t1", cities=("irapuato",), weight=10),
            ),
        )
        result = score_job(_job("Quirkrole Specialist", "Irapuato, Guanajuato"), synthetic)
        assert result is not None
        assert result["score"] == 35
        assert result["matched_role_group"] == "quirk"
        assert result["matched_keyword"] == ""  # no include keyword matched

    def test_role_group_fallback_rejects_when_neither_signal_present(self):
        # Same synthetic profile: a job with no include keyword AND no
        # role-group hit must be rejected even in an allowed city.
        synthetic = AlertProfile(
            name="synthetic",
            email="",
            allowed_cities=("irapuato",),
            include_keywords=("operador",),
            exclude_keywords=(),
            role_groups=(
                RoleGroup(name="quirk", keywords=("quirkrole",), weight=25),
            ),
        )
        assert score_job(_job("Recepcionista", "Irapuato, Guanajuato"), synthetic) is None

    def test_valid_lower_tier_role_still_scores(self):
        # A skilled industrial-trade role (welder) is a lower priority group but
        # must still pass and score; relevance is satisfied via "soldador".
        result = score_job(_job("Soldador", "Salamanca, Guanajuato"), PROFILE)
        assert result is not None
        assert result["score"] == 60  # trade group (30) + Salamanca tier 2 (30)
        assert "industrial trades" in result["matched_role_group"]

    def test_minimal_profile_rejects_irrelevant_allowed_city_job(self):
        # A profile with no role_groups must fall back to include_keywords
        # exactly like the binary matcher: irrelevant role -> reject.
        minimal = AlertProfile(
            name="minimal",
            email="",
            allowed_cities=PROFILE.allowed_cities,
            include_keywords=PROFILE.include_keywords,
            exclude_keywords=PROFILE.exclude_keywords,
        )
        assert score_job(_job("Recepcionista", "Silao, Guanajuato"), minimal) is None

    def test_minimal_profile_accepts_relevant_allowed_city_job(self):
        minimal = AlertProfile(
            name="minimal",
            email="",
            allowed_cities=PROFILE.allowed_cities,
            include_keywords=PROFILE.include_keywords,
            exclude_keywords=PROFILE.exclude_keywords,
        )
        result = score_job(
            _job("Operador de Producción", "Irapuato, Guanajuato"), minimal
        )
        assert result is not None
        assert result["score"] == 0
        assert result["matched_keyword"] == "operador"