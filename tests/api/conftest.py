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
from typing import Optional
from unittest.mock import MagicMock

import pytest

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