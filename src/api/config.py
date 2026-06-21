"""Application configuration via pydantic-settings.

Centralises environment variable reading for the API layer so every
module imports a single ``settings`` instance instead of calling
``os.getenv`` directly. Values fall back to sensible defaults so the
server can start in development without a full ``.env`` file.
"""

import logging
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Typed configuration loaded from environment variables.

    Attributes:
        database_url: SQLAlchemy URL for Supabase PostgreSQL.
        models_bucket: S3 bucket holding XGBoost model artifacts.
        xgboost_model_path: Optional local path to a model.tar.gz file.
        nlp_models_dir: Directory holding BERTopic and FAISS artifacts.
        topic_stats_path: Path to the weekly trends JSON artifact.
        cors_origins: Comma-separated list of allowed CORS origins.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = Field(default="sqlite:///:memory:", alias="DATABASE_URL")
    models_bucket: str = Field(default="hirenovik-models-dev", alias="MODELS_BUCKET")
    xgboost_model_path: str = Field(default="", alias="XGBOOST_MODEL_PATH")
    nlp_models_dir: str = Field(default="src/nlp/models", alias="NLP_MODELS_DIR")
    topic_stats_path: str = Field(
        default="src/nlp/models/topic_stats.json", alias="TOPIC_STATS_PATH"
    )
    cors_origins: str = Field(default="http://localhost:8501", alias="CORS_ORIGINS")

    @property
    def cors_origin_list(self) -> list[str]:
        """Return CORS origins split on commas."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def bertopic_model_path(self) -> str:
        """Return the BERTopic pickle path inside ``nlp_models_dir``."""
        return f"{self.nlp_models_dir}/bertopic_model.pkl"

    @property
    def faiss_index_path(self) -> str:
        """Return the FAISS index path inside ``nlp_models_dir``."""
        return f"{self.nlp_models_dir}/faiss_index.bin"

    @property
    def faiss_id_mapping_path(self) -> str:
        """Return the FAISS id-mapping JSON path inside ``nlp_models_dir``."""
        return f"{self.nlp_models_dir}/id_mapping.json"


@lru_cache
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    logger.debug("Loading API settings from environment")
    return Settings()