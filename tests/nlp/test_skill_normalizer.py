"""Tests for the skill alias normalizer."""

import pytest

from src.nlp.skill_normalizer import normalize_alias, resolve
from src.nlp.skill_taxonomy import load_taxonomy, reset_taxonomy_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_taxonomy_cache()
    yield
    reset_taxonomy_cache()


# ---------------------------------------------------------------------------
# normalize_alias
# ---------------------------------------------------------------------------

class TestNormalizeAlias:
    def test_empty_string(self) -> None:
        assert normalize_alias("") == ""

    def test_whitespace_only(self) -> None:
        assert normalize_alias("   ") == ""

    def test_case_folding(self) -> None:
        assert normalize_alias("Python") == "python"
        assert normalize_alias("PYTHON") == "python"
        assert normalize_alias("PostgreSQL") == "postgresql"

    def test_whitespace_collapse(self) -> None:
        assert normalize_alias("  node   js  ") == "node js"

    def test_hyphen_collapse(self) -> None:
        assert normalize_alias("scikit-learn") == "scikit_learn"
        assert normalize_alias("power-bi") == "power_bi"
        assert normalize_alias("machine-learning") == "machine_learning"

    def test_underscore_collapse(self) -> None:
        assert normalize_alias("scikit_learn") == "scikit_learn"
        assert normalize_alias("power_bi") == "power_bi"

    def test_unicode_normalization(self) -> None:
        assert normalize_alias("héllo") == "héllo"

    def test_preserves_tech_periods(self) -> None:
        """'.' in node.js, .net must be preserved literally."""
        assert normalize_alias("node.js") == "node.js"
        assert normalize_alias(".net") == ".net"

    def test_preserves_plus(self) -> None:
        assert normalize_alias("c++") == "c++"

    def test_preserves_hash(self) -> None:
        assert normalize_alias("c#") == "c#"

    def test_preserves_slash(self) -> None:
        assert normalize_alias("ci/cd") == "ci/cd"


# ---------------------------------------------------------------------------
# resolve (taxonomy-backed)
# ---------------------------------------------------------------------------

class TestResolve:
    @pytest.fixture(scope="class")
    def taxonomy(self):
        return load_taxonomy()

    # PostgreSQL family
    def test_postgresql(self, taxonomy) -> None:
        assert resolve("postgresql", taxonomy).canonical == "postgresql"
        assert resolve("postgres", taxonomy).canonical == "postgresql"
        assert resolve("PostgreSQL", taxonomy).canonical == "postgresql"

    # Node.js family
    def test_nodejs(self, taxonomy) -> None:
        assert resolve("node.js", taxonomy).canonical == "nodejs"
        assert resolve("nodejs", taxonomy).canonical == "nodejs"
        assert resolve("node js", taxonomy).canonical == "nodejs"

    # Power BI family
    def test_power_bi(self, taxonomy) -> None:
        assert resolve("power bi", taxonomy).canonical == "power_bi"
        assert resolve("powerbi", taxonomy).canonical == "power_bi"
        assert resolve("power-bi", taxonomy).canonical == "power_bi"

    # scikit-learn family
    def test_scikit_learn(self, taxonomy) -> None:
        assert resolve("scikit-learn", taxonomy).canonical == "scikit_learn"
        assert resolve("scikit learn", taxonomy).canonical == "scikit_learn"
        assert resolve("sklearn", taxonomy).canonical == "scikit_learn"

    # AWS family
    def test_aws(self, taxonomy) -> None:
        assert resolve("aws", taxonomy).canonical == "aws"
        assert resolve("amazon web services", taxonomy).canonical == "aws"

    # GCP family
    def test_gcp(self, taxonomy) -> None:
        assert resolve("gcp", taxonomy).canonical == "gcp"
        assert resolve("google cloud platform", taxonomy).canonical == "gcp"
        assert resolve("google cloud", taxonomy).canonical == "gcp"

    # C# family
    def test_csharp(self, taxonomy) -> None:
        assert resolve("c#", taxonomy).canonical == "csharp"
        assert resolve("c sharp", taxonomy).canonical == "csharp"
        assert resolve("c-sharp", taxonomy).canonical == "csharp"

    # JavaScript family
    def test_javascript(self, taxonomy) -> None:
        assert resolve("javascript", taxonomy).canonical == "javascript"
        assert resolve("js", taxonomy).canonical == "javascript"
        assert resolve("java script", taxonomy).canonical == "javascript"

    # Unknown
    def test_unknown(self, taxonomy) -> None:
        assert resolve("superunknownskill", taxonomy) is None
        assert resolve("", taxonomy) is None
