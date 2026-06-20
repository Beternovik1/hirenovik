"""FastAPI backend for the Hirenovik job market analytics platform.

The API loads NLP artifacts (embedder, BERTopic model, FAISS index, XGBoost
model) at startup and serves them through REST endpoints for job browsing,
topic exploration, semantic search, and salary prediction.

Modules:
    config: pydantic-settings environment configuration.
    database: SQLAlchemy engine and session factory.
    main: FastAPI application factory and lifespan startup.
"""

__all__: list[str] = []