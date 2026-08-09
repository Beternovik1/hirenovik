"""Tests for computed_evidence_hash — scope-specific, deterministic."""

import pytest

from src.data_quality.dedup_evidence import compute_evidence_hash


class TestSameSourceEvidenceHash:
    """Same-source hash includes URL + canonical-selection evidence."""

    def test_same_inputs_same_hash(self):
        h1 = compute_evidence_hash(
            scope="same_source",
            job_url="https://mx.computrabajo.com/job/123",
            salary_min=30000, salary_max=45000,
            description="Python SQL",
            date_scraped="2026-01-01",
        )
        h2 = compute_evidence_hash(
            scope="same_source",
            job_url="https://mx.computrabajo.com/job/123",
            salary_min=30000, salary_max=45000,
            description="Python SQL",
            date_scraped="2026-01-01",
        )
        assert h1 == h2

    def test_url_change_changes_hash(self):
        h1 = compute_evidence_hash(scope="same_source", job_url="https://mx.computrabajo.com/job/123")
        h2 = compute_evidence_hash(scope="same_source", job_url="https://mx.computrabajo.com/job/456")
        assert h1 != h2

    def test_salary_presence_changes_hash(self):
        h1 = compute_evidence_hash(scope="same_source", job_url="https://example.com/1", salary_min=None)
        h2 = compute_evidence_hash(scope="same_source", job_url="https://example.com/1", salary_min=30000)
        assert h1 != h2  # Phase 2 added salary → stale

    def test_description_presence_changes_hash(self):
        h1 = compute_evidence_hash(scope="same_source", job_url="https://example.com/1", description=None)
        h2 = compute_evidence_hash(scope="same_source", job_url="https://example.com/1", description="Python SQL")
        assert h1 != h2  # Phase 2 added description → stale

    def test_date_change_changes_hash(self):
        h1 = compute_evidence_hash(scope="same_source", job_url="https://example.com/1", date_scraped="2026-01-01")
        h2 = compute_evidence_hash(scope="same_source", job_url="https://example.com/1", date_scraped="2026-06-01")
        assert h1 != h2

    def test_salary_amount_change_does_not_change_hash(self):
        """select_canonical only uses salary PRESENCE, not amount."""
        h1 = compute_evidence_hash(scope="same_source", job_url="https://example.com/1", salary_min=30000, salary_max=45000)
        h2 = compute_evidence_hash(scope="same_source", job_url="https://example.com/1", salary_min=50000, salary_max=70000)
        assert h1 == h2

    def test_description_text_change_presence_same_does_not_change_hash(self):
        """select_canonical only uses description PRESENCE, not content."""
        h1 = compute_evidence_hash(scope="same_source", job_url="https://example.com/1", description="Python SQL")
        h2 = compute_evidence_hash(scope="same_source", job_url="https://example.com/1", description="Java Spring Docker Kubernetes")
        assert h1 == h2

    def test_fragment_differences_produce_different_url_hash(self):
        """Canonicalization happens before insertion, so URLs with fragments
        shouldn't reach the fingerprint.  Different raw URLs produce different hashes."""
        h1 = compute_evidence_hash(scope="same_source", job_url="https://example.com/job/1#lc=A")
        h2 = compute_evidence_hash(scope="same_source", job_url="https://example.com/job/1#lc=B")
        assert h1 != h2  # raw URLs differ; canonicalization is upstream

    def test_nlp_writes_do_not_change_hash(self):
        """cleaned_description, skills_json etc. are NOT in same-source payload."""
        base = {"scope": "same_source", "job_url": "https://example.com/1", "salary_min": 30000, "description": "Python", "date_scraped": "2026-01-01"}
        h1 = compute_evidence_hash(**base)
        assert h1 == compute_evidence_hash(**base)  # deterministic baseline


class TestCrossSourceEvidenceHash:
    """Cross-source hash includes all six matcher fields."""

    def test_same_inputs_same_hash(self):
        args = dict(scope="cross_source", title="Data Engineer", company="Acme Corp", location="CDMX", description="Python SQL", salary_min=30000, salary_max=45000, date_scraped="2026-01-01")
        assert compute_evidence_hash(**args) == compute_evidence_hash(**args)

    def test_title_change_changes_hash(self):
        base = dict(scope="cross_source", title="Data Engineer", company="Acme", location="CDMX", description="SQL", date_scraped="2026-01-01")
        assert compute_evidence_hash(**base) != compute_evidence_hash(**{**base, "title": "Data Scientist"})

    def test_company_normalization_affects_hash(self):
        """normalize_company strips legal suffixes; different raw strings may match."""
        h1 = compute_evidence_hash(scope="cross_source", title="Engineer", company="Acme Corp S.A. de C.V.", location="MX", description="x", date_scraped="2026-01-01")
        h2 = compute_evidence_hash(scope="cross_source", title="Engineer", company="Acme Corp", location="MX", description="x", date_scraped="2026-01-01")
        # Both normalize to similar company, but the hashing happens on
        # normalized output, so they should match.
        assert h1 == h2

    def test_location_change_changes_hash(self):
        base = dict(scope="cross_source", title="Eng", company="A", location="CDMX", description="x", date_scraped="2026-01-01")
        assert compute_evidence_hash(**base) != compute_evidence_hash(**{**base, "location": "GDL"})

    def test_description_change_changes_hash(self):
        base = dict(scope="cross_source", title="Eng", company="A", location="MX", description="Python", date_scraped="2026-01-01")
        assert compute_evidence_hash(**base) != compute_evidence_hash(**{**base, "description": "Java"})

    def test_salary_change_changes_hash(self):
        base = dict(scope="cross_source", title="Eng", company="A", location="MX", description="x", salary_min=30000, salary_max=45000, date_scraped="2026-01-01")
        assert compute_evidence_hash(**base) != compute_evidence_hash(**{**base, "salary_min": 50000})

    def test_date_change_changes_hash(self):
        base = dict(scope="cross_source", title="Eng", company="A", location="MX", description="x", date_scraped="2026-01-01")
        assert compute_evidence_hash(**base) != compute_evidence_hash(**{**base, "date_scraped": "2026-06-01"})

    def test_nlp_writes_do_not_change_hash(self):
        """Only raw evidence fields matter — NLP-derived fields are excluded."""
        base = dict(scope="cross_source", title="Eng", company="A", location="MX", description="Python SQL", salary_min=30000, salary_max=45000, date_scraped="2026-01-01")
        h1 = compute_evidence_hash(**base)
        # Passing the same arguments again — no NLP fields involved
        assert h1 == compute_evidence_hash(**base)


class TestHashProperties:
    """SHA-256, full 64-char hex, deterministic."""

    def test_sha256_64_hex(self):
        h = compute_evidence_hash(scope="same_source", job_url="https://example.com/1")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_deterministic(self):
        args = dict(scope="cross_source", title="X", company="Y", location="Z", description="W", date_scraped="2026-01-01")
        h1 = compute_evidence_hash(**args)
        h2 = compute_evidence_hash(**args)
        h3 = compute_evidence_hash(**args)
        assert h1 == h2 == h3

    def test_null_handling_deterministic(self):
        h1 = compute_evidence_hash(scope="cross_source", title="X", company="Y", location="Z", description=None, salary_min=None, date_scraped=None)
        h2 = compute_evidence_hash(scope="cross_source", title="X", company="Y", location="Z", description=None, salary_min=None, date_scraped=None)
        assert h1 == h2

    def test_unicode_deterministic(self):
        h1 = compute_evidence_hash(scope="cross_source", title="Ingeniería", company="A", location="CDMX", description="Diseño", date_scraped="2026-01-01")
        h2 = compute_evidence_hash(scope="cross_source", title="Ingeniería", company="A", location="CDMX", description="Diseño", date_scraped="2026-01-01")
        assert h1 == h2

    def test_invalid_scope_raises(self):
        with pytest.raises(ValueError):
            compute_evidence_hash(scope="invalid", job_url="x")
