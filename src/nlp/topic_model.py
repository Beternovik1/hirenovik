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

import numpy as np
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

#: Default on-disk path for the topic-coherence JSON artifact.
DEFAULT_COHERENCE_PATH = "src/nlp/models/topic_coherence.json"

#: Default on-disk path for the topic-to-document mapping JSON artifact.
DEFAULT_DOCS_PATH = "src/nlp/models/topic_docs.json"


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
            Defaults to 20 for finer granularity.
        verbose: Whether BERTopic should print progress.
    """

    DEFAULT_MODEL_PATH = DEFAULT_MODEL_PATH
    DEFAULT_KEYWORDS_PATH = DEFAULT_KEYWORDS_PATH
    DEFAULT_COHERENCE_PATH = DEFAULT_COHERENCE_PATH
    DEFAULT_DOCS_PATH = DEFAULT_DOCS_PATH

    def __init__(
        self,
        embedder: Embedder,
        n_gram_range: tuple = (1, 2),
        min_topic_size: int = 20,
        verbose: bool = True,
    ) -> None:
        self.embedder = embedder
        self.n_gram_range = n_gram_range
        self.min_topic_size = min_topic_size
        self.verbose = verbose
        self._model = None
        self._topic_keywords: dict[int, list[str]] = {}
        self._coherence: dict[int, float] = {}
        self._topic_docs: dict[int, list[int]] = {}

    def fit(self, documents: list[str]) -> None:
        """Fit a BERTopic model on ``documents``.

        The effective ``min_topic_size`` is clamped to the number of
        documents so that small training sets do not raise from HDBSCAN
        preconditions. Embeddings come from the configured embedder.

        Args:
            documents: List of cleaned description strings.
        """
        from bertopic import BERTopic
        from bertopic.representation import MaximalMarginalRelevance
        from sklearn.feature_extraction.text import CountVectorizer
        from umap import UMAP
        from hdbscan import HDBSCAN

        # Spanish + English stopwords so common function words do NOT
        # become topic names (e.g. "de_and_en_to" was dominating).
        _ES_STOPWORDS = {
            "de", "la", "que", "el", "en", "y", "a", "los", "se", "del",
            "las", "un", "por", "con", "no", "una", "su", "para", "es",
            "al", "lo", "como", "mas", "pero", "sus", "le", "ya", "o",
            "este", "si", "porque", "esta", "entre", "cuando", "muy",
            "sin", "sobre", "tambien", "me", "hasta", "hay", "donde",
            "quien", "todo", "nos", "durante", "todos", "uno", "les",
            "ni", "contra", "otros", "ese", "eso", "ante", "ellos",
            "e", "esto", "mi", "antes", "algunos", "que", "otro",
            "otras", "otra", "el", "tanto", "esa", "estos", "mucho",
            "poco", "ella", "estar", "estas", "algunas", "algo",
            "nosotros", "mi", "mis", "tu", "te", "ti", "vos",
        }
        _EN_STOPWORDS = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at",
            "to", "for", "of", "with", "from", "by", "as", "is", "was",
            "are", "be", "been", "being", "have", "has", "had", "do",
            "does", "did", "will", "would", "could", "should", "may",
            "might", "can", "shall", "you", "your", "we", "our", "they",
            "them", "their", "it", "its", "he", "she", "his", "her",
            "this", "that", "these", "those", "not", "no", "if", "so",
            "than", "then", "also", "just", "now", "very", "too", "all",
            "some", "any", "each", "every", "both", "few", "more", "most",
            "other", "such", "only", "own", "same", "into", "up", "out",
            "about", "over", "after", "before", "between", "under",
            "again", "further", "here", "there", "when", "where", "why",
            "how", "which", "who", "whom", "what",
        }
        stop_words = list(_ES_STOPWORDS | _EN_STOPWORDS)

        # Minimum 20, but clamp to the document count so small test/training
        # sets don't raise from HDBSCAN preconditions.
        effective_min = min(self.min_topic_size, max(len(documents), 1))
        representation_model = MaximalMarginalRelevance(diversity=0.7)
        vectorizer = CountVectorizer(
            ngram_range=self.n_gram_range, stop_words=stop_words
        )
        umap_model = UMAP(
            n_neighbors=10,
            n_components=3,
            metric="cosine",
            random_state=42,
            low_memory=False,
        )
        hdbscan_model = HDBSCAN(
            min_cluster_size=effective_min,
            min_samples=1,
            metric="euclidean",
            cluster_selection_method="eom",
            prediction_data=True,
        )
        # NOTE: nr_topics is intentionally NOT set — let HDBSCAN find
        # natural clusters rather than forcing auto-reduction.
        self._model = BERTopic(
            embedding_model=self.embedder._model if self.embedder._model else None,
            umap_model=umap_model,
            hdbscan_model=hdbscan_model,
            vectorizer_model=vectorizer,
            representation_model=representation_model,
            verbose=self.verbose,
            calculate_probabilities=True,
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

        # Populate the topic-to-document mapping for later inspection.
        self._topic_docs = {}
        for job_id, topic_id in mapping.items():
            self._topic_docs.setdefault(int(topic_id), []).append(int(job_id))

        self._persist_topics(mapping)
        logger.info("Assigned topics to %d jobs", len(mapping))
        return mapping

    def get_topic_docs(self, topic_id: int) -> list[int]:
        """Return the job ids assigned to ``topic_id``.

        Args:
            topic_id: BERTopic topic identifier.

        Returns:
            List of job ids assigned to the topic, or an empty list if
            the topic has no documents or has not been assigned.
        """
        return list(self._topic_docs.get(int(topic_id), []))

    def get_representative_docs(
        self,
        df: pd.DataFrame,
        embeddings: np.ndarray,
        n: int = 3,
    ) -> dict[int, list[str]]:
        """Return the n most central documents per topic.

        Centrality is measured by cosine similarity to the topic
        centroid. Requires a previously fit model with topic
        assignments stored in ``df``.

        Args:
            df: DataFrame with ``id``, ``cleaned_description``, and
                ``topic_id`` columns.
            embeddings: Array aligned with ``df`` rows containing
                precomputed document embeddings.
            n: Number of representative docs to return per topic.

        Returns:
            Mapping ``{topic_id: [doc_text, ...]}`` for all topics
            except -1. Each list has at most ``n`` entries.
        """
        embeddings = np.asarray(embeddings, dtype=np.float32)
        if embeddings.ndim != 2:
            raise ValueError("embeddings must be a 2D array")
        if embeddings.shape[0] != len(df):
            raise ValueError("embeddings and df must have the same length")

        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        normalized = embeddings / norms

        result: dict[int, list[str]] = {}
        topic_ids = df["topic_id"].astype(int).tolist()
        descriptions = df["cleaned_description"].tolist()

        for topic_id in sorted(set(topic_ids)):
            if topic_id == -1:
                continue
            positions = [i for i, t in enumerate(topic_ids) if t == topic_id]
            if len(positions) <= 1:
                result[int(topic_id)] = [descriptions[positions[0]]]
                continue
            members = normalized[positions]
            centroid = members.mean(axis=0, keepdims=True)
            centroid_norm = np.linalg.norm(centroid, axis=1, keepdims=True)
            centroid_norm = np.where(centroid_norm == 0, 1.0, centroid_norm)
            centroid = centroid / centroid_norm
            sims = members @ centroid.reshape(-1)
            top_idx = np.argsort(sims)[::-1][:n]
            result[int(topic_id)] = [descriptions[positions[i]] for i in top_idx]

        return result

    def compute_coherence(
        self,
        embeddings: np.ndarray,
        topic_assignments: list[int],
    ) -> dict[int, float]:
        """Compute per-topic coherence as mean centroid cosine similarity.

        For each topic, the centroid of its assigned embeddings is
        computed and the average cosine similarity of the members to the
        centroid is returned. Embeddings are L2-normalized before the
        similarity is computed so the metric ranges from -1 to 1.

        Args:
            embeddings: ``(n_docs, dim)`` float32 array of document
                embeddings aligned with ``topic_assignments``.
            topic_assignments: Topic id for each row in ``embeddings``.

        Returns:
            Mapping ``{topic_id: coherence_float}`` excluding topic -1.
            Topics with 0-1 documents have coherence ``0.0``.
        """
        embeddings = np.asarray(embeddings, dtype=np.float32)
        if embeddings.ndim != 2:
            raise ValueError("embeddings must be a 2D array (n_docs, dim)")
        if embeddings.shape[0] != len(topic_assignments):
            raise ValueError(
                "embeddings and topic_assignments must have the same length"
            )

        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        normalized = embeddings / norms

        unique_topics = set(int(t) for t in topic_assignments)
        coherence: dict[int, float] = {}
        for topic_id in unique_topics:
            if topic_id == -1:
                continue
            positions = [
                i for i, t in enumerate(topic_assignments) if int(t) == topic_id
            ]
            if len(positions) <= 1:
                coherence[int(topic_id)] = 0.0
                continue
            members = normalized[positions]
            centroid = members.mean(axis=0, keepdims=True)
            centroid_norm = np.linalg.norm(centroid, axis=1, keepdims=True)
            centroid_norm = np.where(centroid_norm == 0, 1.0, centroid_norm)
            centroid_normalized = centroid / centroid_norm
            sims = members @ centroid_normalized.reshape(-1)
            coherence[int(topic_id)] = float(sims.mean())

        self._coherence = coherence
        logger.info("Computed coherence for %d topics", len(coherence))
        return coherence

    def get_coherence(self) -> dict[int, float]:
        """Return the cached coherence mapping ``{topic_id: float}``.

        The mapping is populated by :meth:`compute_coherence` or loaded
        from disk by :meth:`load`. Returns an empty dict if coherence
        has not been computed.
        """
        return dict(self._coherence)

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
        if self._coherence:
            with open(self.DEFAULT_COHERENCE_PATH, "w", encoding="utf-8") as fh:
                json.dump(
                    {str(k): v for k, v in self._coherence.items()},
                    fh,
                    ensure_ascii=False,
                    indent=2,
                )
        if self._topic_docs:
            with open(self.DEFAULT_DOCS_PATH, "w", encoding="utf-8") as fh:
                json.dump(
                    {str(k): v for k, v in self._topic_docs.items()},
                    fh,
                    ensure_ascii=False,
                    indent=2,
                )
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
        # Load coherence from disk if available.
        coherence: dict[int, float] = {}
        if os.path.exists(cls.DEFAULT_COHERENCE_PATH):
            try:
                with open(cls.DEFAULT_COHERENCE_PATH, encoding="utf-8") as fh:
                    coherence = {
                        int(k): float(v) for k, v in json.load(fh).items()
                    }
            except (json.JSONDecodeError, ValueError):
                coherence = {}
        instance._coherence = coherence
        # Load topic->docs mapping from disk if available.
        topic_docs: dict[int, list[int]] = {}
        if os.path.exists(cls.DEFAULT_DOCS_PATH):
            try:
                with open(cls.DEFAULT_DOCS_PATH, encoding="utf-8") as fh:
                    topic_docs = {
                        int(k): [int(i) for i in v]
                        for k, v in json.load(fh).items()
                    }
            except (json.JSONDecodeError, ValueError):
                topic_docs = {}
        instance._topic_docs = topic_docs
        return instance


__all__: list[str] = [
    "TopicModel",
    "DEFAULT_MODEL_PATH",
    "DEFAULT_KEYWORDS_PATH",
    "DEFAULT_COHERENCE_PATH",
    "DEFAULT_DOCS_PATH",
]