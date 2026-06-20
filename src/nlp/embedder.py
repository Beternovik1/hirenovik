"""Sentence-transformers embedder with transparent disk cache.

Wraps a multilingual SentenceTransformer to produce dense embeddings for
job descriptions and short keyword queries. Embeddings for individual texts
are cached on disk using a SHA-256 of the input as the cache key, so
repeated runs and interactive FastAPI requests do not recompute
embeddings for previously seen text.
"""

import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

#: Default multilingual model; small and fast, supports es/en.
DEFAULT_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

#: Default cache directory under the project data folder.
DEFAULT_CACHE_DIR = "data/embeddings_cache"

#: File extension for cached embedding arrays.
_CACHE_EXT = ".npy"


class Embedder:
    """Embed text using a SentenceTransformer model with disk caching.

    Args:
        model_name: HuggingFace model identifier. Defaults to a small
            multilingual MiniLM suitable for ES/EN job descriptions.
        cache_dir: Directory used to persist per-text embeddings as
            ``.npy`` files keyed by the SHA-256 of the input text.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        cache_dir: str = DEFAULT_CACHE_DIR,
    ) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self._model = None

    def _init_model(self) -> None:
        """Lazy-load the SentenceTransformer model on first use.

        Importing :class:`sentence_transformers.SentenceTransformer` is
        deferred so that importing this module (e.g. for tests) does
        not require the heavy dependency.
        """
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info("Loading SentenceTransformer model: %s", self.model_name)
            self._model = SentenceTransformer(self.model_name)

    def encode_batch(
        self,
        texts: list[str],
        batch_size: int = 32,
        show_progress: bool = True,
    ) -> np.ndarray:
        """Encode a list of texts into a dense numpy array.

        Args:
            texts: List of input strings.
            batch_size: Batch size passed to the underlying model.
            show_progress: Whether to render a progress bar.

        Returns:
            Array of shape ``(len(texts), embedding_dim)``.
        """
        self._init_model()
        embeddings = self._model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=show_progress,
            convert_to_numpy=True,
        )
        return np.asarray(embeddings)

    def encode_single(self, text: str) -> np.ndarray:
        """Encode a single string, transparently consulting the cache.

        Args:
            text: Input string.

        Returns:
            Embedding vector of shape ``(embedding_dim,)``.
        """
        cached = self._read_cache(text)
        if cached is not None:
            logger.debug("Cache hit for embedding")
            return cached
        self._init_model()
        embedding = self._model.encode([text], convert_to_numpy=True)[0]
        embedding = np.asarray(embedding)
        self._write_cache(text, embedding)
        return embedding

    def get_embedding_dim(self) -> int:
        """Return the embedding dimension of the loaded model."""
        self._init_model()
        return int(self._model.get_sentence_embedding_dimension())

    def _cache_path(self, text: str) -> str:
        """Return the on-disk cache file path for ``text``.

        Uses a SHA-256 hex digest of the input text so the path is
        deterministic and stable across processes.
        """
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        file_name = digest + _CACHE_EXT
        return os.path.join(self.cache_dir, file_name)

    def _read_cache(self, text: str) -> Optional[np.ndarray]:
        """Return cached embedding for ``text`` or ``None`` on a miss."""
        path = self._cache_path(text)
        if not os.path.exists(path):
            return None
        try:
            return np.load(path)
        except (OSError, ValueError) as exc:
            logger.warning("Corrupt cache file %s: %s", path, exc)
            return None

    def _write_cache(self, text: str, embedding: np.ndarray) -> None:
        """Persist an embedding to disk keyed by ``text``."""
        path = self._cache_path(text)
        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)
        np.save(path, embedding)
        logger.debug("Wrote cache for embedding to %s", path)