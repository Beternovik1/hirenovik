"""Tests for Computrabajo URL canonicalization."""

import pytest
from scrapers.computrabajo_scraper import canonicalize_computrabajo_url


class TestCanonicalizeComputrabajoUrl:
    def test_removes_fragment(self) -> None:
        url = "https://mx.computrabajo.com/ofertas/job-ABC123#lc=ListOffers-Score4-11"
        result = canonicalize_computrabajo_url(url)
        assert result == "https://mx.computrabajo.com/ofertas/job-ABC123"

    def test_different_fragments_collapse_to_same_url(self) -> None:
        a = canonicalize_computrabajo_url(
            "https://mx.computrabajo.com/ofertas/job-ABC123#lc=ListOffers-Score4-11"
        )
        b = canonicalize_computrabajo_url(
            "https://mx.computrabajo.com/ofertas/job-ABC123#lc=ListOffers-Score4-12"
        )
        assert a == b == "https://mx.computrabajo.com/ofertas/job-ABC123"

    def test_preserves_query_parameters(self) -> None:
        url = (
            "https://mx.computrabajo.com/ofertas/job-ABC123"
            "?ref=search&order=date#lc=ListOffers-Score4-11"
        )
        result = canonicalize_computrabajo_url(url)
        assert result == (
            "https://mx.computrabajo.com/ofertas/job-ABC123"
            "?ref=search&order=date"
        )

    def test_no_fragment_returns_unchanged(self) -> None:
        url = "https://mx.computrabajo.com/ofertas/job-ABC123"
        result = canonicalize_computrabajo_url(url)
        assert result == url

    def test_no_fragment_with_query_returns_unchanged(self) -> None:
        url = "https://mx.computrabajo.com/ofertas/job-ABC123?ref=search"
        result = canonicalize_computrabajo_url(url)
        assert result == url

    def test_non_score_fragment_also_removed(self) -> None:
        """All fragments are removed — not just #lc= patterns."""
        url = "https://mx.computrabajo.com/job/123#any-other-fragment"
        result = canonicalize_computrabajo_url(url)
        assert result == "https://mx.computrabajo.com/job/123"

    def test_empty_string(self) -> None:
        assert canonicalize_computrabajo_url("") == ""

    def test_none_returns_empty(self) -> None:
        assert canonicalize_computrabajo_url(None) == ""

    def test_preserves_port(self) -> None:
        url = "https://mx.computrabajo.com:8080/job/123#lc=ListOffers-Score4-11"
        result = canonicalize_computrabajo_url(url)
        assert result == "https://mx.computrabajo.com:8080/job/123"

    def test_malformed_url_falls_back(self) -> None:
        """urlsplit gracefully strips the ### fragment."""
        result = canonicalize_computrabajo_url("not-a-valid-url###")
        assert result == "not-a-valid-url"
