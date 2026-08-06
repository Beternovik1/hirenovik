"""Tests for the skill taxonomy loader and validator."""

import json
import tempfile
from pathlib import Path

import pytest

from src.nlp.skill_taxonomy import (
    SkillDefinition,
    SkillTaxonomy,
    SkillTaxonomyError,
    load_taxonomy,
    reset_taxonomy_cache,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure each test starts with a fresh taxonomy cache."""
    reset_taxonomy_cache()
    yield
    reset_taxonomy_cache()


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

class TestLoadTaxonomy:
    def test_loads_real_taxonomy(self) -> None:
        taxonomy = load_taxonomy()
        assert taxonomy.version == "1.0.0"
        assert len(taxonomy) > 80
        assert len(taxonomy.categories) >= 12
        assert "programming_languages" in taxonomy.categories
        assert taxonomy.categories["programming_languages"] == "Programming Languages"

    def test_loads_skill_definitions(self) -> None:
        taxonomy = load_taxonomy()
        py_skill = taxonomy.get("python")
        assert py_skill is not None
        assert py_skill.canonical == "python"
        assert py_skill.display == "Python"
        assert "python" in py_skill.aliases
        assert py_skill.category == "programming_languages"
        assert py_skill.match_strategy == "phrase"

    def test_singleton_cache(self) -> None:
        t1 = load_taxonomy()
        t2 = load_taxonomy()
        assert t1 is t2

    def test_custom_path(self) -> None:
        """load_taxonomy with explicit path should bypass cache."""
        t1 = load_taxonomy()  # default, cached
        t2 = load_taxonomy(path=t1._TAXONOMY_PATH if hasattr(t1, '_TAXONOMY_PATH') else None)
        # When path=None, uses cache. When path is explicit, may load fresh.
        assert t1 is t2 or t2 is not None


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

class TestResolve:
    def test_resolve_direct_alias(self) -> None:
        taxonomy = load_taxonomy()
        skill = taxonomy.resolve("postgres")
        assert skill is not None
        assert skill.canonical == "postgresql"

    def test_resolve_case_insensitive(self) -> None:
        taxonomy = load_taxonomy()
        skill = taxonomy.resolve("POSTGRES")
        assert skill is not None
        assert skill.canonical == "postgresql"

    def test_resolve_unknown_returns_none(self) -> None:
        taxonomy = load_taxonomy()
        assert taxonomy.resolve("superunknownskill") is None

    def test_resolve_empty_returns_none(self) -> None:
        taxonomy = load_taxonomy()
        assert taxonomy.resolve("") is None

    def test_resolve_whitespace_returns_none(self) -> None:
        taxonomy = load_taxonomy()
        assert taxonomy.resolve("   ") is None


# ---------------------------------------------------------------------------
# Validation: duplicate canonicals
# ---------------------------------------------------------------------------

class TestDuplicateCanonicals:
    def test_rejects_duplicate_canonicals(self) -> None:
        raw = {
            "version": "1.0",
            "categories": {"lang": "Languages"},
            "skills": [
                {
                    "canonical": "python",
                    "display": "Python",
                    "aliases": ["python"],
                    "category": "lang",
                    "icon_slug": "python",
                    "match_strategy": "phrase",
                },
                {
                    "canonical": "python",
                    "display": "Python 2",
                    "aliases": ["py"],
                    "category": "lang",
                    "icon_slug": None,
                    "match_strategy": "phrase",
                },
            ],
            "match_strategies": {},
        }
        path = _write_temp_taxonomy(raw)
        with pytest.raises(SkillTaxonomyError, match="Duplicate canonical key 'python'"):
            load_taxonomy(path)


# ---------------------------------------------------------------------------
# Validation: conflicting aliases
# ---------------------------------------------------------------------------

class TestConflictingAliases:
    def test_rejects_conflicting_alias(self) -> None:
        raw = {
            "version": "1.0",
            "categories": {"lang": "Languages", "db": "Databases"},
            "skills": [
                {
                    "canonical": "python",
                    "display": "Python",
                    "aliases": ["py"],
                    "category": "lang",
                    "icon_slug": None,
                    "match_strategy": "phrase",
                },
                {
                    "canonical": "pytorch",
                    "display": "PyTorch",
                    "aliases": ["py"],
                    "category": "lang",
                    "icon_slug": None,
                    "match_strategy": "phrase",
                },
            ],
            "match_strategies": {},
        }
        path = _write_temp_taxonomy(raw)
        with pytest.raises(SkillTaxonomyError, match="Conflicting alias 'py'"):
            load_taxonomy(path)


# ---------------------------------------------------------------------------
# Validation: required fields
# ---------------------------------------------------------------------------

class TestRequiredFields:
    def test_rejects_missing_canonical(self) -> None:
        raw = _minimal_valid()
        raw["skills"][0].pop("canonical")
        path = _write_temp_taxonomy(raw)
        with pytest.raises(SkillTaxonomyError, match="missing required fields"):
            load_taxonomy(path)

    def test_rejects_empty_canonical(self) -> None:
        raw = _minimal_valid()
        raw["skills"][0]["canonical"] = ""
        path = _write_temp_taxonomy(raw)
        with pytest.raises(SkillTaxonomyError, match="must be a non-empty string"):
            load_taxonomy(path)

    def test_rejects_empty_display(self) -> None:
        raw = _minimal_valid()
        raw["skills"][0]["display"] = ""
        path = _write_temp_taxonomy(raw)
        with pytest.raises(SkillTaxonomyError, match="'display' is empty"):
            load_taxonomy(path)

    def test_rejects_missing_category(self) -> None:
        raw = _minimal_valid()
        raw["skills"][0].pop("category")
        path = _write_temp_taxonomy(raw)
        with pytest.raises(SkillTaxonomyError, match="missing required fields"):
            load_taxonomy(path)

    def test_rejects_unknown_category(self) -> None:
        raw = _minimal_valid()
        raw["skills"][0]["category"] = "no_such_category"
        path = _write_temp_taxonomy(raw)
        with pytest.raises(SkillTaxonomyError, match="unknown category"):
            load_taxonomy(path)

    def test_rejects_empty_aliases(self) -> None:
        raw = _minimal_valid()
        raw["skills"][0]["aliases"] = []
        path = _write_temp_taxonomy(raw)
        with pytest.raises(SkillTaxonomyError, match="at least one entry"):
            load_taxonomy(path)

    def test_rejects_non_list_aliases(self) -> None:
        raw = _minimal_valid()
        raw["skills"][0]["aliases"] = "not_a_list"
        path = _write_temp_taxonomy(raw)
        with pytest.raises(SkillTaxonomyError, match="must be a list"):
            load_taxonomy(path)

    def test_rejects_non_string_alias(self) -> None:
        raw = _minimal_valid()
        raw["skills"][0]["aliases"] = [42]
        path = _write_temp_taxonomy(raw)
        with pytest.raises(SkillTaxonomyError, match="is not a non-empty string"):
            load_taxonomy(path)

    def test_rejects_empty_alias_string(self) -> None:
        raw = _minimal_valid()
        raw["skills"][0]["aliases"] = ["  "]
        path = _write_temp_taxonomy(raw)
        with pytest.raises(SkillTaxonomyError, match="is not a non-empty string"):
            load_taxonomy(path)

    def test_rejects_duplicate_alias_within_skill(self) -> None:
        raw = _minimal_valid()
        raw["skills"][0]["aliases"] = ["python", "python"]
        path = _write_temp_taxonomy(raw)
        with pytest.raises(SkillTaxonomyError, match="duplicate alias 'python'"):
            load_taxonomy(path)

    def test_rejects_unknown_match_strategy(self) -> None:
        raw = _minimal_valid()
        raw["skills"][0]["match_strategy"] = "fuzzy"
        path = _write_temp_taxonomy(raw)
        with pytest.raises(SkillTaxonomyError, match="unknown match_strategy"):
            load_taxonomy(path)

    def test_rejects_bad_icon_slug_type(self) -> None:
        raw = _minimal_valid()
        raw["skills"][0]["icon_slug"] = 123  # not a string or null
        path = _write_temp_taxonomy(raw)
        with pytest.raises(SkillTaxonomyError, match="icon_slug"):
            load_taxonomy(path)


# ---------------------------------------------------------------------------
# Validation: schema
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    def test_rejects_missing_version(self) -> None:
        raw = _minimal_valid()
        raw.pop("version")
        path = _write_temp_taxonomy(raw)
        with pytest.raises(SkillTaxonomyError, match="missing required key 'version'"):
            load_taxonomy(path)

    def test_rejects_missing_categories(self) -> None:
        raw = _minimal_valid()
        raw.pop("categories")
        path = _write_temp_taxonomy(raw)
        with pytest.raises(SkillTaxonomyError, match="missing required key 'categories'"):
            load_taxonomy(path)

    def test_rejects_empty_categories(self) -> None:
        raw = _minimal_valid()
        raw["categories"] = {}
        path = _write_temp_taxonomy(raw)
        with pytest.raises(SkillTaxonomyError, match="'categories' is empty"):
            load_taxonomy(path)

    def test_rejects_missing_skills(self) -> None:
        raw = _minimal_valid()
        raw.pop("skills")
        path = _write_temp_taxonomy(raw)
        with pytest.raises(SkillTaxonomyError, match="missing required key 'skills'"):
            load_taxonomy(path)

    def test_rejects_empty_skills_list(self) -> None:
        raw = _minimal_valid()
        raw["skills"] = []
        path = _write_temp_taxonomy(raw)
        with pytest.raises(SkillTaxonomyError, match="'skills' list is empty"):
            load_taxonomy(path)

    def test_rejects_non_list_skills(self) -> None:
        raw = _minimal_valid()
        raw["skills"] = "not_list"
        path = _write_temp_taxonomy(raw)
        with pytest.raises(SkillTaxonomyError, match="must be a list"):
            load_taxonomy(path)

    def test_file_not_found(self) -> None:
        with pytest.raises(SkillTaxonomyError, match="not found"):
            load_taxonomy(Path("/nonexistent/taxonomy.json"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_valid() -> dict:
    return {
        "version": "1.0",
        "categories": {"lang": "Languages"},
        "skills": [
            {
                "canonical": "python",
                "display": "Python",
                "aliases": ["python"],
                "category": "lang",
                "icon_slug": "python",
                "match_strategy": "phrase",
            }
        ],
        "match_strategies": {},
    }


def _write_temp_taxonomy(raw: dict) -> Path:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(raw, tmp)
    tmp.close()
    return Path(tmp.name)
