"""FastAPI application with optimistic model loading at startup.

The app loads four NLP/ML artifacts into ``app.state`` on startup:
embedder, BERTopic topic model, FAISS search engine, and XGBoost model.
Loading is optimistic: if any artifact is missing or fails to load, the
app still starts and the affected endpoints return HTTP 503.
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.config import get_settings

logger = logging.getLogger(__name__)


def _try_load_embedder() -> Optional[object]:
    """Attempt to instantiate the Embedder; return None on failure."""
    try:
        from src.nlp.embedder import Embedder

        embedder = Embedder()
        logger.info("Embedder loaded (model will lazy-init on first encode)")
        return embedder
    except Exception:  # noqa: BLE001 - optimistic load logs and continues
        logger.warning("Embedder unavailable; semantic search will return 503")
        return None


def _try_load_topic_model() -> Optional[object]:
    """Attempt to load the BERTopic model; return None on failure."""
    try:
        from src.nlp.topic_model import TopicModel

        embedder = _try_load_embedder()
        if embedder is None:
            logger.warning("TopicModel unavailable: embedder not loaded")
            return None
        # Force embedder init so the SentenceTransformer can be injected
        # into the deserialized BERTopic model (stripped during save).
        embedder._init_model()
        settings = get_settings()
        model = TopicModel.load(path=settings.bertopic_model_path, embedder=embedder)
        logger.info("TopicModel loaded from %s", settings.bertopic_model_path)
        return model
    except Exception:  # noqa: BLE001 - optimistic load logs and continues
        logger.warning(
            "TopicModel unavailable; topic endpoints will return 503. "
            "Run python -m src.nlp.pipeline first."
        )
        return None


def _try_load_search_engine() -> Optional[object]:
    """Attempt to load the FAISS search engine; return None on failure."""
    try:
        from src.nlp.search_engine import SearchEngine

        embedder = _try_load_embedder()
        if embedder is None:
            logger.warning("SearchEngine unavailable: embedder not loaded")
            return None
        settings = get_settings()
        engine = SearchEngine.load(
            embedder=embedder,
            index_path=settings.faiss_index_path,
            id_mapping_path=settings.faiss_id_mapping_path,
        )
        logger.info("SearchEngine loaded from %s", settings.faiss_index_path)
        return engine
    except Exception:  # noqa: BLE001 - optimistic load logs and continues
        logger.warning(
            "SearchEngine unavailable; search endpoints will return 503. "
            "Run python -m src.nlp.pipeline first."
        )
        return None


def _try_load_xgboost() -> Optional[object]:
    """Attempt to load the XGBoost model; return None on failure."""
    try:
        from src.api.services.predict_service import load_xgboost

        model = load_xgboost()
        if model is not None:
            logger.info("XGBoost model loaded successfully")
        else:
            logger.warning(
                "XGBoost unavailable; prediction endpoint will return 503"
            )
        return model
    except Exception:  # noqa: BLE001 - optimistic load logs and continues
        logger.warning("XGBoost unavailable; prediction endpoint will return 503")
        return None


@asynccontextmanager
async def lifespan(app: FastAPI) -> None:
    """Load all NLP/ML artifacts into ``app.state`` on startup."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("Starting Hirenovik API: loading NLP/ML artifacts")

    app.state.embedder = _try_load_embedder()
    app.state.topic_model = _try_load_topic_model()
    app.state.search_engine = _try_load_search_engine()
    app.state.xgboost = _try_load_xgboost()

    logger.info("Startup complete; app ready to serve requests")
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    app = FastAPI(
        title="Hirenovik API",
        description="Job market analytics with NLP topic modeling and salary prediction",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.settings = settings

    from src.api.routers import analytics, jobs, topics, trends, skills, search, predict

    app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
    app.include_router(topics.router, prefix="/topics", tags=["topics"])
    app.include_router(trends.router, prefix="/trends", tags=["trends"])
    app.include_router(skills.router, prefix="/skills", tags=["skills"])
    app.include_router(search.router, prefix="/search", tags=["search"])
    app.include_router(predict.router, prefix="/predict", tags=["predict"])
    app.include_router(analytics.router)

    @app.get("/", tags=["health"])
    def health_check() -> dict:  # type: ignore[no-untyped-def]
        """Return service health and model availability status."""
        return {
            "status": "ok",
            "service": "hirenovik-api",
            "models": {
                "embedder": app.state.embedder is not None,
                "topic_model": app.state.topic_model is not None,
                "search_engine": app.state.search_engine is not None,
                "xgboost": app.state.xgboost is not None,
            },
        }

    return app


app = create_app()
