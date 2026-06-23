"""Outlier detection via PCA + IsolationForest on sentence embeddings.

Computes or loads cached embeddings, applies dynamic PCA
dimensionality reduction, and flags semantic outliers so the
downstream topic model is not polluted by documents far from any
cluster. Maintains strict row alignment between the returned
DataFrame and the ``embeddings_clean`` numpy array.

Cache is keyed by a SHA-256 hash of the concatenated cleaned
description texts (we load from Supabase, not CSV files) and stored
under the same ``data/embeddings_cache/`` directory used by the
:class:`Embedder`.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

#: Default multilingual model; small and fast, supports es/en.
DEFAULT_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

#: Default cache directory shared with the Embedder.
DEFAULT_CACHE_DIR = "data/embeddings_cache"

#: Maximum number of PCA components (capped by sample count minus one).
MAX_PCA_COMPONENTS = 50

#: IsolationForest expected proportion of outliers in the dataset.
DEFAULT_CONTAMINATION = 0.10

#: Reproducibility seed for PCA and IsolationForest.
RANDOM_SEED = 42


class OutlierDetector:
    """Detect semantic outliers using PCA-reduced sentence embeddings.

    Args:
        embedding_model: A ``SentenceTransformer`` instance, or ``None``
            to lazy-load :data:`DEFAULT_MODEL_NAME` on first use.
        contamination: Expected proportion of outliers in the dataset.
            Must be between 0.01 and 0.15.
        cache_dir: Directory for per-dataset cache subfolders. Defaults
            to :data:`DEFAULT_CACHE_DIR` so embeddings are shared with
            the :class:`Embedder`.
    """

    def __init__(
        self,
        embedding_model=None,
        contamination: float = DEFAULT_CONTAMINATION,
        cache_dir: str = DEFAULT_CACHE_DIR,
    ) -> None:
        self._model = embedding_model
        self._contamination = contamination
        self._cache_dir = Path(cache_dir)

    # ── Public API ──────────────────────────────────────────────────

    def run(
        self, df: pd.DataFrame
    ) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray]:
        """Detect outliers and return aligned clean/outlier splits.

        Args:
            df: DataFrame with a ``cleaned_description`` column.

        Returns:
            Tuple of ``(df_clean, df_outliers, embeddings_clean)``
            where ``embeddings_clean.shape[0] == len(df_clean)``.
        """
        embeddings = self._get_embeddings(df)

        # Guard: empty embeddings (no valid text to encode) — return
        # everything as clean so downstream topic modeling still has data.
        if len(embeddings) == 0:
            logger.warning(
                "No embeddings produced (all documents empty?). "
                "Returning full DataFrame as clean with empty embeddings."
            )
            return (
                df.reset_index(drop=True),
                df.head(0).reset_index(drop=True),
                np.empty((0, 0), dtype=np.float32),
            )

        mask = self._detect(embeddings)

        df_clean = df[mask].reset_index(drop=True)
        df_outliers = df[~mask].reset_index(drop=True)

        # Apply the same boolean mask to the embeddings array so rows
        # stay aligned with df_clean.
        embeddings_clean = embeddings[mask]

        logger.info(
            "Outliers: %d / %d (%.1f%%). Clean: %d.",
            len(df_outliers),
            len(df),
            (len(df_outliers) / len(df) * 100) if len(df) else 0.0,
            len(df_clean),
        )

        return df_clean, df_outliers, embeddings_clean

    # ── Embedding computation / cache ──────────────────────────────

    def _compute_hash(self, df: "pd.DataFrame") -> str:
        """SHA-256 of concatenated ``cleaned_description`` values."""
        combined = "".join(df["cleaned_description"].tolist()).encode("utf-8")
        return hashlib.sha256(combined).hexdigest()

    def _init_model(self) -> None:
        """Lazy-load the default SentenceTransformer when none was provided."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info(
                "Loading SentenceTransformer for outlier detection: %s",
                DEFAULT_MODEL_NAME,
            )
            self._model = SentenceTransformer(DEFAULT_MODEL_NAME)

    def _get_embeddings(self, df: "pd.DataFrame") -> np.ndarray:
        """Return full embeddings (load cached or compute)."""
        current_hash = self._compute_hash(df)
        embeddings = self._try_load_cache(current_hash)

        if embeddings is not None:
            logger.info("Loaded outlier embeddings from cache (hash match).")
            return embeddings

        self._init_model()
        logger.info("Computing embeddings for %d documents ...", len(df))
        embeddings = self._model.encode(
            df["cleaned_description"].tolist(),
            show_progress_bar=True,
        )
        embeddings = np.array(embeddings)

        self._save_cache(embeddings, current_hash)
        return embeddings

    def _cache_path(self, hash_val: str) -> Path:
        """Return the cache directory for a given content hash."""
        return self._cache_dir / f"outlier_{hash_val[:16]}"

    def _try_load_cache(self, current_hash: str) -> Optional[np.ndarray]:
        """Load cached embeddings if the hash matches."""
        cache_path = self._cache_path(current_hash)
        emb_path = cache_path / "embeddings.npy"
        hash_path = cache_path / "cache_hash.txt"

        if not emb_path.exists() or not hash_path.exists():
            return None

        saved_hash = hash_path.read_text(encoding="utf-8").strip()
        if saved_hash != current_hash:
            logger.warning(
                "Outlier cache invalidated: text content changed. Recomputing."
            )
            return None

        logger.debug("Outlier cache hit at %s", cache_path)
        return np.load(emb_path)

    def _save_cache(self, embeddings: np.ndarray, hash_val: str) -> None:
        """Persist embeddings and hash to the cache directory."""
        cache_path = self._cache_path(hash_val)
        cache_path.mkdir(parents=True, exist_ok=True)

        emb_path = cache_path / "embeddings.npy"
        hash_path = cache_path / "cache_hash.txt"
        np.save(emb_path, embeddings)
        hash_path.write_text(hash_val, encoding="utf-8")

        logger.info("Outlier embeddings cached to %s", cache_path)

    # ── PCA + IsolationForest ───────────────────────────────────────

    def _detect(self, embeddings: np.ndarray) -> np.ndarray:
        """Return boolean mask: ``True`` = clean (inlier).

        Args:
            embeddings: Full-dimensional embeddings array.

        Returns:
            Boolean numpy array aligned with ``embeddings`` rows.
        """
        n = len(embeddings)

        if n <= 1:
            logger.warning(
                "Too few samples (%d) for PCA + IsolationForest. "
                "Marking all as inliers.",
                n,
            )
            return np.ones(n, dtype=bool)

        n_components = min(MAX_PCA_COMPONENTS, n - 1)
        logger.info(
            "PCA n_components=%d (embeddings shape: %s).",
            n_components,
            embeddings.shape,
        )

        from sklearn.decomposition import PCA
        from sklearn.ensemble import IsolationForest

        pca = PCA(n_components=n_components, random_state=RANDOM_SEED)
        reduced = pca.fit_transform(embeddings)

        logger.debug(
            "PCA explained variance ratio: %.4f (sum of %d components).",
            pca.explained_variance_ratio_.sum(),
            n_components,
        )

        iso = IsolationForest(
            contamination=self._contamination,
            random_state=RANDOM_SEED,
        )
        iso.fit(reduced)

        logger.debug(
            "IsolationForest parameters: contamination=%.2f, random_state=%d.",
            self._contamination,
            RANDOM_SEED,
        )

        # IsolationForest returns 1 for inliers, -1 for outliers.
        predictions = iso.predict(reduced)
        return predictions == 1


__all__: list[str] = ["OutlierDetector"]