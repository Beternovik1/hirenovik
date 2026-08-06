"""Tests for the deterministic SkillExtractor engine — part 1 (basic, aliases, false positives, punctuation)."""

import pytest

from src.nlp.skill_extractor import SkillExtractor, get_extractor, reset_extractor
from src.nlp.skill_taxonomy import reset_taxonomy_cache


@pytest.fixture(autouse=True)
def _clear_state():
    reset_taxonomy_cache()
    reset_extractor()
    yield
    reset_taxonomy_cache()
    reset_extractor()


class TestBasicMatching:
    @pytest.fixture(scope="class")
    def extractor(self):
        return SkillExtractor()

    def test_python(self, extractor) -> None:
        result = extractor.extract("We need a Python developer with Django")
        assert "python" in result
        assert "django" in result

    def test_sql(self, extractor) -> None:
        assert "sql" in extractor.extract("Looking for a SQL expert")

    def test_docker(self, extractor) -> None:
        assert "docker" in extractor.extract("Experience with Docker containers")

    def test_kubernetes(self, extractor) -> None:
        assert "kubernetes" in extractor.extract("Kubernetes cluster management")

    def test_airflow(self, extractor) -> None:
        assert "airflow" in extractor.extract("Apache Airflow data pipelines")

    def test_power_bi(self, extractor) -> None:
        assert "power_bi" in extractor.extract("Experience with Power BI dashboards")

    def test_postgresql(self, extractor) -> None:
        assert "postgresql" in extractor.extract("PostgreSQL database administration")

    def test_aws(self, extractor) -> None:
        assert "aws" in extractor.extract("AWS cloud infrastructure")

    def test_react(self, extractor) -> None:
        result = extractor.extract("React developer with TypeScript")
        assert "react" in result
        assert "typescript" in result

    def test_fastapi(self, extractor) -> None:
        assert "fastapi" in extractor.extract("Building APIs with FastAPI")


class TestAliases:
    @pytest.fixture(scope="class")
    def extractor(self):
        return SkillExtractor()

    def test_postgresql_postgres(self, extractor) -> None:
        assert "postgresql" in extractor.extract("Postgres database")

    def test_nodejs_variants(self, extractor) -> None:
        assert "nodejs" in extractor.extract("Node.js developer")
        assert "nodejs" in extractor.extract("NodeJS backend")
        assert "nodejs" in extractor.extract("Node JS experience")

    def test_power_bi_variants(self, extractor) -> None:
        assert "power_bi" in extractor.extract("Power BI dashboards")
        assert "power_bi" in extractor.extract("PowerBI reports")
        assert "power_bi" in extractor.extract("Power-BI analytics")

    def test_scikit_learn_variants(self, extractor) -> None:
        assert "scikit_learn" in extractor.extract("scikit-learn models")
        assert "scikit_learn" in extractor.extract("sklearn pipelines")
        assert "scikit_learn" in extractor.extract("scikit learn tutorials")

    def test_aws_amazon(self, extractor) -> None:
        assert "aws" in extractor.extract("AWS cloud")
        assert "aws" in extractor.extract("Amazon Web Services")

    def test_gcp(self, extractor) -> None:
        assert "gcp" in extractor.extract("Google Cloud Platform")
        assert "gcp" in extractor.extract("Google Cloud")

    def test_csharp_variants(self, extractor) -> None:
        assert "csharp" in extractor.extract("C# developer")
        assert "csharp" in extractor.extract("C sharp programming")
        assert "csharp" in extractor.extract("C-sharp backend")

    def test_javascript_variants(self, extractor) -> None:
        assert "javascript" in extractor.extract("JavaScript frontend")
        assert "javascript" in extractor.extract("JS developer")
        assert "javascript" in extractor.extract("Java Script experience")


class TestFalsePositives:
    @pytest.fixture(scope="class")
    def extractor(self):
        return SkillExtractor()

    def test_go_not_ongoing(self, extractor) -> None:
        assert "go" not in extractor.extract("This is an ongoing project")

    def test_scala_not_scalable(self, extractor) -> None:
        assert "scala" not in extractor.extract("We need scalable architecture")

    def test_java_not_in_javascript(self, extractor) -> None:
        result = extractor.extract("JavaScript developer needed")
        assert "javascript" in result
        assert "java" not in result

    def test_access_not_generic(self, extractor) -> None:
        assert "access" not in extractor.extract("You need access to the database")

    def test_react_not_generic(self, extractor) -> None:
        assert "react" not in extractor.extract("You must react quickly to incidents")

    def test_random_c_not_matched(self, extractor) -> None:
        assert "c" not in extractor.extract("a b c d e f g")

    def test_random_r_not_matched(self, extractor) -> None:
        assert "r" not in extractor.extract("a b r d e f g")

    def test_bare_node_not_matched(self, extractor) -> None:
        assert "nodejs" not in extractor.extract("the node in the cluster")


class TestPunctuationTechnologies:
    @pytest.fixture(scope="class")
    def extractor(self):
        return SkillExtractor()

    def test_cpp(self, extractor) -> None:
        assert "c_plus_plus" in extractor.extract("C++ developer")

    def test_csharp(self, extractor) -> None:
        assert "csharp" in extractor.extract("C# experience")

    def test_dotnet(self, extractor) -> None:
        assert "dotnet" in extractor.extract(".NET framework developer")

    def test_node_dot_js(self, extractor) -> None:
        assert "nodejs" in extractor.extract("Node.js backend")

    def test_cicd(self, extractor) -> None:
        assert "ci_cd" in extractor.extract("CI/CD pipeline engineer")


class TestDeduplication:
    @pytest.fixture(scope="class")
    def extractor(self):
        return SkillExtractor()

    def test_repeated_same_mention(self, extractor) -> None:
        result = extractor.extract("Python Python Python is great")
        assert result.count("python") <= 1

    def test_multiple_aliases_same_skill(self, extractor) -> None:
        result = extractor.extract("Node.js, NodeJS and Node JS are all the same")
        assert result.count("nodejs") <= 1

    def test_case_variants(self, extractor) -> None:
        result = extractor.extract("PYTHON Python python")
        assert sum(1 for s in result if s == "python") <= 1

    def test_punctuation_variants(self, extractor) -> None:
        result = extractor.extract("C# and C-sharp are the same")
        assert sum(1 for s in result if s == "csharp") <= 1


class TestLanguageSupport:
    @pytest.fixture(scope="class")
    def extractor(self):
        return SkillExtractor()

    def test_english(self, extractor) -> None:
        result = extractor.extract("Experience with Python and SQL required")
        assert "python" in result
        assert "sql" in result

    def test_spanish(self, extractor) -> None:
        result = extractor.extract("experiencia con Python y SQL")
        assert "python" in result
        assert "sql" in result

    def test_spanish_power_bi(self, extractor) -> None:
        assert "power_bi" in extractor.extract("manejo de Power BI")

    def test_spanish_aws(self, extractor) -> None:
        assert "aws" in extractor.extract("servicios de Amazon Web Services")

    def test_spanish_nodejs(self, extractor) -> None:
        assert "nodejs" in extractor.extract("desarrollo con Node.js")

    def test_spanish_supply_chain(self, extractor) -> None:
        assert "supply_chain" in extractor.extract("experiencia en cadena de suministro")

    def test_spanish_sap(self, extractor) -> None:
        result = extractor.extract("conocimiento de SAP MM y SAP WM")
        assert "sap_mm" in result
        assert "sap_wm" in result

    def test_spanish_lean(self, extractor) -> None:
        assert "lean_manufacturing" in extractor.extract("implementacion de lean manufacturing")

    def test_mixed_language(self, extractor) -> None:
        result = extractor.extract("Buscamos un Python developer con experiencia en PostgreSQL y AWS")
        assert "python" in result
        assert "postgresql" in result
        assert "aws" in result


class TestInputHandling:
    @pytest.fixture(scope="class")
    def extractor(self):
        return SkillExtractor()

    def test_none_returns_empty(self, extractor) -> None:
        assert extractor.extract(None) == []

    def test_empty_string_returns_empty(self, extractor) -> None:
        assert extractor.extract("") == []

    def test_whitespace_only_returns_empty(self, extractor) -> None:
        assert extractor.extract("   \t\n  ") == []

    def test_very_long_description(self, extractor) -> None:
        text = "Python and SQL " * 500
        result = extractor.extract(text)
        assert "python" in result
        assert "sql" in result

    def test_unicode_punctuation(self, extractor) -> None:
        result = extractor.extract("Python \u2013 SQL \u2014 Docker\u2026")
        assert "python" in result
        assert "sql" in result
        assert "docker" in result

    def test_accented_spanish(self, extractor) -> None:
        result = extractor.extract("experiencia con Python en integracion continua")
        assert "python" in result

    def test_rejects_int_type(self, extractor) -> None:
        with pytest.raises(TypeError):
            extractor.extract(42)

    def test_rejects_list_type(self, extractor) -> None:
        with pytest.raises(TypeError):
            extractor.extract(["Python"])


class TestOutputContract:
    @pytest.fixture(scope="class")
    def extractor(self):
        return SkillExtractor()

    def test_returns_list(self, extractor) -> None:
        assert isinstance(extractor.extract("Python"), list)

    def test_no_duplicates(self, extractor) -> None:
        result = extractor.extract("python python PYTHON")
        assert len(result) == len(set(result))

    def test_sorted_alphabetically(self, extractor) -> None:
        result = extractor.extract("Docker, AWS, Python, SQL, Kubernetes")
        assert result == sorted(result)

    def test_no_raw_aliases(self, extractor) -> None:
        result = extractor.extract("Node.js and Postgres")
        assert "node.js" not in result
        assert "postgres" not in result
        assert "nodejs" in result
        assert "postgresql" in result


class TestMatcherReuse:
    def test_patterns_compiled_once(self) -> None:
        extractor = SkillExtractor()
        assert extractor.pattern_count > 0
        patterns = extractor._patterns.patterns
        extractor.extract("Python")
        assert extractor._patterns.patterns is patterns


class TestExplicitMentionPolicy:
    @pytest.fixture(scope="class")
    def extractor(self):
        return SkillExtractor()

    def test_postgresql_alone_no_sql(self, extractor) -> None:
        result = extractor.extract("PostgreSQL database")
        assert "postgresql" in result
        assert "sql" not in result

    def test_both_explicitly_mentioned(self, extractor) -> None:
        result = extractor.extract("PostgreSQL and SQL experience")
        assert "postgresql" in result
        assert "sql" in result


class TestSingleton:
    def test_get_extractor_returns_singleton(self) -> None:
        e1 = get_extractor()
        e2 = get_extractor()
        assert e1 is e2
