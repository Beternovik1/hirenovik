"""BERTopic topic model with fitting and DB assignment.

Builds a topic model from job descriptions using UMAP + HDBSCAN +
CountVectorizer over embeddings produced by an :class:`Embedder`s.
Topics are persisted to disk as a pickle of the BERTopic model and a
JSON file of topic keywords. The same class also persists results to
Supabase by storing the topic id and topic keywords in the existing
``keywords_json`` JSONB column of the jobs table.
"""

import json
import logging
import os
import pickle
from typing import Optional

import pandas as pd
from sqlalchemy import update
from sqlalchemy.orm import Session

from src.database.models import Job, db_connect
from src.nlp.embedder import Embedder

logger = logging.getLogger(__name__)

#: Default on-disk path for the pickled BERTopic model.
DEFAULT_MODEL_PATH = "src/nlp/models/bertopic_model.pkl"

#: Default on-disk path for the topic-keywords JSON artifact.
DEFAULT_KEYWORDS_PATH = "src/nlp/models/topic_keywords.json"


class TopicModel:
    """Wrap a BERTopic model for topic discovery and DB assignment.

    The model is fit lazily in :meth:`fit` so constructing the class is
    cheap; the heavy dependency on BERTopic (and therefore sklearn, UMAP,
    HDBSCAN) is only pulled in when fitting or transforming is requested.

    Args:
        embedder: Embedder used to produce document embeddings.
        n_gram_range: n-gram range passed to the CountVectorizer.
        min_topic_size: HDBSCAN ``min_topic_size``; small document sets
            are handled gracefully by lowering this to the document count.
        verbose: Whether BERTopic should print progress.
    """

    DEFAULT_MODEL_PATH = DEFAULT_MODEL_PATH
    DEFAULT_KEYWORDS_PATH = DEFAULT_KEYWORDS_PATH

    def __init__(
        self,
        embedder: Embedder,
        n_gram_range: tuple = (1, 2),
        min_topic_size: int = 10,
        verbose: bool = True,
    ) -> None:
        self.embedder = embedder
        self.n_gram_range = n_gram_range
        self.min_topic_size = min_topic_size
        self.verbose = verbose
        self._model = None
        self._topic_keywords: dict[int, list[str]] = {}

    def fit(self, documents: list[str]) -> None:
        """Fit a BERTopic model on ``documents``.

        The effective ``min_topic_size`` is clamped to the number of
        documents so that small training sets do not raise from HDBSCAN
        preconditions. Embeddings come from the configured embedder.

        Args:
            documents: List of cleaned description strings.
        """
        from bertopic import BERTopic
        from sklearn.feature_extraction.text import CountVectorizer
        from umap import UMAP
        from hdbscan import HDBSCAN

        effective_min = min(self.min_topic_size, max(len(documents), 1))
        vectorizer = CountVectorizer(ngram_range=self.n_gram_range)
        umap_model = UMAP(n_neighbors=min(15, max(len(documents), 2)), random_state=42)
        hdbscan_model = HDBSCAN(min_topic_size=effective_min)
        self._model = BERTopic(
            embedding_model=self.embedder._model if self.embedder._model else None,
            umap_model=umap_model,
            hdbscan_model=hdbscan_model,
            vectorizer_model=vectorizer,
            verbose=self.verbose,
            calculate_probabilities=False,
        )
        self._model.fit_transform(documents)
        self._refresh_topic_keywords()
        logger.info(
            "TopicModel fit on %d documents (min_topic_size=%d)",
            len(documents),
            effective_min,
        )

    def _refresh_topic_keywords(self) -> None:
        """Populate :attr:`_topic_keywords` from the fitted model."""
        if self._model is None:
            self._topic_keywords = {}
            return
        topics = self._model.get_topics()
        self._topic_keywords = {
            int(topic_id): [word for word, _ in words]
            for topic_id, words in topics.items()
        }

    def get_topic_info(self) -> pd.DataFrame:
        """Return BERTopic's topic info DataFrame."""
        if self._model is None:
            raise RuntimeError("TopicModel must be fit before calling get_topic_info")
        return self._model.get_topic_info()

    def get_topic_keywords(self) -> dict[int, list[str]]:
        """Return a mapping of topic id to top keywords."""
        return self._topic_keywords

    def assign_topics(self, documents: list[str]) -> list[int]:
        """Return the topic id assigned to each document.

        Args:
            documents: Input strings to assign.

        Returns:
            List of integer topic ids aligned with ``documents``.
        """
        if self._model is None:
            raise RuntimeError("TopicModel must be fit before calling assign_topics")
        topics, _ = self._model.transform(documents)
        return [int(t) for t in topics]

    def assign_to_db(
        self,
        df: pd.DataFrame,
        topic_column: str = "topic_id",
    ) -> dict[int, int]:
        """Assign topics to documents and persist them to Supabase.

        Args:
            df: DataFrame with ``id`` and ``cleaned_description`` columns.
            topic_column: Name of the column to write into the result
                mapping (informational only).

        Returns:
            Mapping ``{job_id: topic_id}``.

        Raises:
            RuntimeError: If no documents are provided.
        """
        if "id" not in df.columns or "cleaned_description" not in df.columns:
            raise ValueError("DataFrame must have 'id' and 'cleaned_description' columns")
        if len(df) == 0:
            return {}

        documents = df["cleaned_description"].tolist()
        topics = self.assign_topics(documents)
        job_ids = [int(jid) for jid in df["id"].tolist()]
        mapping: dict[int, int] = {
            job_ids[i]: int(topics[i]) for i in range(len(job_ids))
        }

        self._persist_topics(mapping)
        logger.info("Assigned topics to %d jobs", len(mapping))
        return mapping

    def _persist_topics(self, mapping: dict[int, int]) -> None:
        """Update keywords_json in Supabase for each job in ``mapping``."""
        engine = db_connect()
        try:
            with Session(engine) as session:
                for job_id, topic_id in mapping.items():
                    payload = {
                        "topic_id": int(topic_id),
                        "topic_keywords": self._topic_keywords.get(int(topic_id), []),
                    }
                    session.execute(
                        update(Job)
                        .where(Job.id == job_id)
                        .values(keywords_json=payload)
                    )
                session.commit()
        finally:
            engine.dispose()

    def save(self, path: str = DEFAULT_MODEL_PATH) -> None:
        """Pickle the fitted BERTopic model to ``path``.

        The embedder is intentionally NOT pickled because it holds heavy
        external state and is expected to be injected on load.

        Args:
            path: Destination file path.
        """
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as fh:
            pickle.dump(self._model, fh)
        with open(self.DEFAULT_KEYWORDS_PATH, "w", encoding="utf-8") as fh:
            json.dump(self._topic_keywords, fh, ensure_ascii=False, indent=2)
        logger.info("Saved TopicModel to %s", path)

    @classmethod
    def load(
        cls,
        path: str = DEFAULT_MODEL_PATH,
        embedder: Optional[Embedder] = None,
    ) -> "TopicModel":
        """Load a TopicModel from ``path``.

        Args:
            path: Path to a pickle produced by :meth:`save`.
            embedder: Embedder to bind to the loaded model (the embedder
                is not stored in the pickle).

        Returns:
            A new :class:`TopicModel` with the fitted model hydrated.
        """
        with open(path, "rb") as fh:
            model = pickle.load(fh)
        os.makedirs(os.path.dirname(cls.DEFAULT_KEYWORDS_PATH) or ".", exist_ok=True)
        topic_keywords: dict[int, list[str]] = {}
        if os.path.exists(cls.DEFAULT_KEYWORDS_PATH):
            with open(cls.DEFAULT_KEYWORDS_PATH, encoding="utf-8") as fh:
                topic_keywords = {
                    int(k): list(v) for k, v in json.load(fh).items()
                }
        instance = cls(embedder=embedder) if embedder is not None else cls(embedder=Embedder())
        instance._model = model
        instance._topic_keywords = topic_keywords
        return instance


__all__: list[str] = ["TopicModel", "DEFAULT_MODEL_PATH", "DEFAULT_KEYWORDS_PATH"]