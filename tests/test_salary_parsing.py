"""Tests for _parse_salary() in ComputrabajoScraper and OCCScraper.

Both scrapers have an identical _parse_salary() static method. These tests
verify both produce consistent results — including the NaN regression case
that caused silent salary corruption in production.
"""

import math

import pytest

from scrapers.computrabajo_scraper import ComputrabajoScraper
from scrapers.occ_scraper import OCCScraper


# Test both implementations with the same inputs
PARSERS = [
    ("Computrabajo", ComputrabajoScraper._parse_salary),
    ("OCC", OCCScraper._parse_salary),
]


class TestParseSalary:
    @pytest.mark.parametrize("name,parser", PARSERS)
    def test_parse_salary_comma_range(self, name, parser):
        min_sal, max_sal = parser("$25,000 a $35,000")
        assert min_sal == 25000.0, f"{name}: min_sal"
        assert max_sal == 35000.0, f"{name}: max_sal"

    @pytest.mark.parametrize("name,parser", PARSERS)
    def test_parse_salary_single_amount(self, name, parser):
        min_sal, max_sal = parser("$15,000")
        assert min_sal == 15000.0, f"{name}"
        assert max_sal == 15000.0, f"{name}"

    @pytest.mark.parametrize("name,parser", PARSERS)
    def test_parse_salary_without_dollar_sign(self, name, parser):
        min_sal, max_sal = parser("15,000 a 20,000")
        assert min_sal == 15000.0, f"{name}"
        assert max_sal == 20000.0, f"{name}"

    @pytest.mark.parametrize("name,parser", PARSERS)
    def test_parse_salary_with_decimal(self, name, parser):
        min_sal, max_sal = parser("$1,500.50 a $2,000.75")
        assert min_sal == 1500.50, f"{name}"
        assert max_sal == 2000.75, f"{name}"

    @pytest.mark.parametrize("name,parser", PARSERS)
    def test_parse_salary_returns_none_for_negotiable(self, name, parser):
        min_sal, max_sal = parser("A convenir")
        assert min_sal is None, f"{name}"
        assert max_sal is None, f"{name}"

    @pytest.mark.parametrize("name,parser", PARSERS)
    def test_parse_salary_returns_none_for_empty_string(self, name, parser):
        min_sal, max_sal = parser("")
        assert min_sal is None, f"{name}"
        assert max_sal is None, f"{name}"

    @pytest.mark.parametrize("name,parser", PARSERS)
    def test_parse_salary_returns_none_for_none_input(self, name, parser):
        min_sal, max_sal = parser(None)
        assert min_sal is None, f"{name}"
        assert max_sal is None, f"{name}"

    @pytest.mark.parametrize("name,parser", PARSERS)
    def test_parse_salary_regression_nan_does_not_corrupt(self, name, parser):
        """NaN input should return None, never the string 'NaN'."""
        min_sal, max_sal = parser(str(float("nan")))
        assert min_sal is None, f"{name}: min_sal should be None, got {min_sal}"
        assert max_sal is None, f"{name}: max_sal should be None, got {max_sal}"

    @pytest.mark.parametrize("name,parser", PARSERS)
    def test_parse_salary_three_amounts_takes_first_two(self, name, parser):
        min_sal, max_sal = parser("$10,000 $20,000 $30,000")
        assert min_sal == 10000.0, f"{name}"
        assert max_sal == 20000.0, f"{name}"

    @pytest.mark.parametrize("name,parser", PARSERS)
    def test_parse_salary_text_with_extra_words(self, name, parser):
        min_sal, max_sal = parser("Sueldo mensual: $12,000 a $18,000 MXN")
        assert min_sal == 12000.0, f"{name}"
        assert max_sal == 18000.0, f"{name}"
