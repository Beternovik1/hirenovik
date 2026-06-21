"""Pytest fixtures for the API test suite.

The API imports heavy NLP/ML artifacts at startup. To keep tests fast
and isolated, we stub the NLP classes in ``sys.modules`` before the
FastAPI app is imported, then mock the database engine with an
in-memory SQLite stub. Routers are registered incrementally via the
``app`` fixture so tests can override ``app.state`` per test.
"""

import logging
import sys
import types
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock

import pytest
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

logging.disable(logging.CRITICAL)


@pytest.fixture
def mock_nlp_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub heavy NLP classes in sys.modules so imports stay cheap.

    Real ``sentence_transformers``, ``bertopic``, and ``faiss`` are not
    installed during tests. We inject fake modules so that importing
    ``src.nlp.embedder``, ``src.nlp.topic_model``, and
    ``src.nlp.search_engine`` succeeds without network or model downloads.
    """
    for mod_name in ("sentence_transformers",):
        if mod_name not in sys.modules:
            fake = types.ModuleType(mod_name)
            fake.SentenceTransformer = MagicMock()
            monkeypatch.setitem(sys.modules, mod_name, fake)

    # Stub bertopic
    fake_bertopic = types.ModuleType("bertopic")
    fake_bertopic.BERTopic = MagicMock()
    if "bertopic" not in sys.modules:
        monkeypatch.setitem(sys.modules, "bertopic", fake_bertopic)

    # Stub faiss
    if "faiss" not in sys.modules:
        fake_faiss = types.ModuleType("faiss")
        fake_faiss.IndexFlatIP = MagicMock()
        fake_faiss.read_index = MagicMock()
        fake_faiss.write_index = MagicMock()
        monkeypatch.setitem(sys.modules, "faiss", fake_faiss)


@pytest.fixture
def mock_embedder() -> MagicMock:
    """Return a MagicMock standing in for the Embedder."""
    embedder = MagicMock()
    embedder.get_embedding_dim.return_value = 384
    return embedder


@pytest.fixture
def mock_topic_model() -> MagicMock:
    """Return a MagicMock standing in for the TopicModel."""
    return MagicMock()


@pytest.fixture
def mock_search_engine() -> MagicMock:
    """Return a MagicMock standing in for the SearchEngine."""
    return MagicMock()


@pytest.fixture
def app(
    monkeypatch: pytest.MonkeyPatch,
    mock_nlp_modules: None,
) -> "object":
    """Return a FastAPI app instance with routers and mocked state.

    Avoids real DB connections by pointing the engine at an in-memory
    database and skipping the lifespan model loading (tests inject mocks
    into ``app.state`` directly).
    """
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("XGBOOST_MODEL_PATH", "")

    # Reset cached settings and database engine so env vars take effect.
    from src.api.config import get_settings
    from src.api import database as db_module

    get_settings.cache_clear()
    db_module.reset_engine()

    from src.api.main import create_app

    application = create_app()

    # Register routers incrementally as they are added per commit.
    _register_routers(application)

    # Inject None so models are unavailable unless a test sets them.
    application.state.embedder = None
    application.state.topic_model = None
    application.state.search_engine = None
    application.state.xgboost = None

    return application


def _register_routers(application: object) -> None:
    """Import and register all routers that exist at the current commit."""
    router_imports: list[tuple[str, str]] = [
        ("jobs", "src.api.routers.jobs"),
        ("topics", "src.api.routers.topics"),
        ("trends", "src.api.routers.trends"),
        ("skills", "src.api.routers.skills"),
        ("search", "src.api.routers.search"),
        ("predict", "src.api.routers.predict"),
    ]
    for prefix, import_path in router_imports:
        try:
            module = __import__(import_path, fromlist=["router"])
            application.include_router(module.router, prefix=f"/{prefix}", tags=[prefix])
        except ImportError:
            pass


@pytest.fixture
def client(app) -> "object":
    """Return a Starlette TestClient bound to the test app."""
    from starlette.testclient import TestClient

    return TestClient(app)


@pytest.fixture
def mock_db_session(app):
    """Create a SQLite in-memory session with the jobs table and sample data.

    Uses StaticPool so every connection shares the same in-memory database.
    Registers a ``get_db`` override on the app so FastAPI routes use this
    session instead of the production engine.
    """
    from sqlalchemy import StaticPool
    from src.api.database import get_db
    from src.database.models import Base, Job

    # Swap JSONB -> JSON so SQLite can create the jobs table.
    original_type = Job.__table__.c.keywords_json.type
    Job.__table__.c.keywords_json.type = JSON()

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    session = Session(engine, expire_on_commit=False)
    now = datetime.now(tz=timezone.utc)
    sample_jobs = [
        Job(
            id=1,
            site="indeed",
            job_url="https://indeed.com/job/1",
            title="DATA ENGINEER",
            company="Tech Corp",
            raw_location="Leon, GTO",
            country="Mexico",
            country_code="MX",
            state="Guanajuato",
            career="Data Engineer",
            industry_niche="Ingenieria de Datos",
            job_type="remoto",
            salary_min=25000,
            salary_max=40000,
            currency="MXN",
            description="Build data pipelines",
            status="NEW",
            date_scraped=now,
            last_updated=now,
        ),
        Job(
            id=2,
            site="computrabajo",
            job_url="https://computrabajo.com/job/2",
            title="CLOUD ENGINEER",
            company="Cloud Inc",
            raw_location="Remoto",
            country="Mexico",
            country_code="MX",
            career="Cloud Engineer",
            industry_niche="Infraestructura Cloud",
            job_type="remoto",
            salary_min=30000,
            salary_max=50000,
            currency="MXN",
            description="Manage cloud infrastructure",
            status="NEW",
            date_scraped=now,
            last_updated=now,
        ),
        Job(
            id=3,
            site="occ",
            job_url="https://occ.com/job/3",
            title="DATA ANALYST",
            company="Analytics Co",
            raw_location="CDMX",
            country="Mexico",
            country_code="MX",
            state="CDMX",
            career="Data Analyst",
            industry_niche="Ingenieria de Datos",
            job_type="presencial",
            description="Analyze data",
            status="NEW",
            date_scraped=now,
            last_updated=now,
        ),
    ]
    session.add_all(sample_jobs)
    session.commit()

    # Override the get_db dependency to yield our test session.
    def _override():
        yield session

    app.dependency_overrides[get_db] = _override

    yield session

    app.dependency_overrides.clear()
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()
    # Restore original JSONB type so other test modules are not affected.
    Job.__table__.c.keywords_json.type = original_type