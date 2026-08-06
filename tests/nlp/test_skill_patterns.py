"""Tests for the skill pattern compiler."""

import pytest

from src.nlp.skill_patterns import build_patterns, SkillPatternError
from src.nlp.skill_taxonomy import load_taxonomy, reset_taxonomy_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_taxonomy_cache()
    yield
    reset_taxonomy_cache()


@pytest.fixture(scope="module")
def bank():
    taxonomy = load_taxonomy()
    return build_patterns(taxonomy)


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------

class TestCompilation:
    def test_patterns_compiled(self, bank) -> None:
        """Every alias produces exactly one compiled pattern."""
        assert len(bank.patterns) > 0
        for pattern, canonical, alias in bank.patterns:
            assert isinstance(canonical, str)
            assert isinstance(alias, str)
            assert hasattr(pattern, "search")

    def test_all_canonicals_set(self, bank) -> None:
        assert "python" in bank.all_canonicals
        assert "postgresql" in bank.all_canonicals
        assert "csharp" in bank.all_canonicals


# ---------------------------------------------------------------------------
# Phrase matching
# ---------------------------------------------------------------------------

class TestPhraseMatching:
    def test_simple_word_match(self, bank) -> None:
        found = bank.match("We need a Python developer")
        assert "python" in found

    def test_case_insensitive(self, bank) -> None:
        found = bank.match("Experience with PYTHON")
        assert "python" in found

    def test_word_boundary_prevents_substring(self, bank) -> None:
        """'java' must not match inside 'javascript'."""
        found = bank.match("JavaScript developer needed")
        assert "java" not in found

    def test_scala_not_scalable(self, bank) -> None:
        found = bank.match("scalable architecture")
        assert "scala" not in found

    def test_go_not_ongoing(self, bank) -> None:
        found = bank.match("ongoing project")
        assert "go" not in found

    def test_multi_word_aliases(self, bank) -> None:
        """Multi-word aliases are matched as phrases."""
        found = bank.match("amazon web services experience")
        assert "aws" in found

    def test_postgresql_aliases(self, bank) -> None:
        found = bank.match("Looking for a PostgreSQL DBA")
        assert "postgresql" in found
        found2 = bank.match("Looking for a Postgres expert")
        assert "postgresql" in found2


# ---------------------------------------------------------------------------
# Symbol-aware matching
# ---------------------------------------------------------------------------

class TestSymbolAwareMatching:
    def test_c_plus_plus(self, bank) -> None:
        found = bank.match("Experience with C++")
        assert "c_plus_plus" in found

    def test_csharp(self, bank) -> None:
        found = bank.match("C# developer needed")
        assert "csharp" in found

    def test_dotnet(self, bank) -> None:
        found = bank.match("Experience with .NET framework")
        assert "dotnet" in found

    def test_ci_cd(self, bank) -> None:
        found = bank.match("Experience with CI/CD pipelines")
        assert "ci_cd" in found


# ---------------------------------------------------------------------------
# Ambiguous-term safety
# ---------------------------------------------------------------------------

class TestAmbiguousTermSafety:
    def test_c_not_bare_letter(self, bank) -> None:
        """Bare 'c' should not match; only multi-word phrases like 'c programming'."""
        found = bank.match("this is a c test")
        # "c" alone is not a taxonomy alias; multi-word phrases are.
        assert "c" not in found

    def test_c_in_context(self, bank) -> None:
        found = bank.match("experience in c programming and embedded systems")
        assert "c" in found

    def test_r_not_bare_letter(self, bank) -> None:
        found = bank.match("this is an r test")
        assert "r" not in found

    def test_r_in_context(self, bank) -> None:
        found = bank.match("experience in r programming and statistics")
        assert "r" in found

    def test_go_not_bare_word(self, bank) -> None:
        found = bank.match("you should go to the office")
        assert "go" not in found

    def test_go_in_context(self, bank) -> None:
        found = bank.match("seeking go programming expert")
        assert "go" in found

    def test_react_not_generic(self, bank) -> None:
        found = bank.match("you need to react quickly")
        assert "react" not in found

    def test_react_in_context(self, bank) -> None:
        found = bank.match("react developer with typescript")
        assert "react" in found

    def test_access_not_generic(self, bank) -> None:
        found = bank.match("you need access to the system")
        assert "access" not in found

    def test_access_in_context(self, bank) -> None:
        found = bank.match("experience with microsoft access databases")
        assert "access" in found
