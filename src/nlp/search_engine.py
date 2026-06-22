"""FAISS-based search engine with iterative query expansion.

Builds a cosine-similarity index over job description embeddings and
provides three query modes: a direct query, an iterative
query-expansion over a seed text, and a keyword-list average query.
Embeddings are L2-normalized so a flat inner-product index yields
cosine rankings. The index and an id-mapping JSON are persisted to
disk for reuse from FastAPI without rebuilding.
"""

import json
import logging
import os
from typing import Optional

import numpy as np

from src.nlp.embedder import Embedder

logger = logging.getLogger(__name__)

#: Default on-disk path for the serialized FAISS index.
DEFAULT_INDEX_PATH = "src/nlp/models/faiss_index.bin"

#: Default on-disk path for the index-to-job_id mapping JSON.
DEFAULT_ID_MAPPING_PATH = "src/nlp/models/id_mapping.json"

#: Default on-disk path for the raw embedding matrix (float32 .npy).
DEFAULT_EMBEDDINGS_PATH = "src/nlp/models/embeddings.npy"


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    """Return an L2-normalized copy of ``matrix`` along axis 1."""
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return matrix / norms


class SearchEngine:
    """Cosine similarity search over embeddings via FAISS.

    Args:
        embedder: Embedder used to encode query and document text.
        index_path: File path for the serialized FAISS index.
        id_mapping_path: File path for the JSON id-mapping artifact.
    """

    DEFAULT_INDEX_PATH = DEFAULT_INDEX_PATH
    DEFAULT_ID_MAPPING_PATH = DEFAULT_ID_MAPPING_PATH
    DEFAULT_EMBEDDINGS_PATH = DEFAULT_EMBEDDINGS_PATH

    def __init__(
        self,
        embedder: Embedder,
        index_path: str = DEFAULT_INDEX_PATH,
        id_mapping_path: str = DEFAULT_ID_MAPPING_PATH,
    ) -> None:
        self.embedder = embedder
        self.index_path = index_path
        self.id_mapping_path = id_mapping_path
        self._index = None
        self._id_mapping: list[int] = []
        self._documents: list[str] = []
        self._embeddings: Optional[np.ndarray] = None

    def build_index(self, documents: list[str], doc_ids: list[int]) -> None:
        """Embed and index the given documents.

        Embeddings are L2-normalized and stored in a flat inner-product
        FAISS index. The original documents and embeddings are kept in
        memory so :meth:`expand` can recompute centroids during query
        expansion.

        Args:
            documents: Cleaned description strings.
            doc_ids: Job ids aligned with ``documents``.
        """
        if len(documents) != len(doc_ids):
            raise ValueError("documents and doc_ids must have the same length")

        # Deduplicate by job_id keeping the first occurrence so the same
        # document cannot appear multiple times in the index (which would
        # otherwise produce identical scores for different returned rows).
        unique: dict[int, tuple[str, int]] = {}
        order: list[int] = []
        for doc, jid in zip(documents, doc_ids):
            jid_int = int(jid)
            if jid_int in unique:
                continue
            unique[jid_int] = (doc, jid_int)
            order.append(jid_int)
        removed_count = len(doc_ids) - len(order)
        if removed_count > 0:
            logger.warning(
                "Deduplicated %d duplicate job_ids from index", removed_count
            )
        documents = [unique[jid][0] for jid in order]
        doc_ids = [unique[jid][1] for jid in order]

        import faiss

        embeddings = self.embedder.encode_batch(
            documents, batch_size=32, show_progress=False
        )
        embeddings = np.asarray(embeddings, dtype=np.float32)
        embeddings = _l2_normalize(embeddings)

        dim = int(embeddings.shape[1])
        index = faiss.IndexFlatIP(dim)
        index.add(embeddings)

        self._index = index
        self._id_mapping = [int(i) for i in doc_ids]
        self._documents = list(documents)
        self._embeddings = embeddings
        logger.info(
            "Built FAISS index with %d vectors of dim %d",
            len(documents),
            dim,
        )

    def query(self, text: str, k: int = 10) -> list[dict]:
        """Query the index with ``text`` and return top ``k`` results.

        Args:
            text: Input query string.
            k: Number of results to return.

        Returns:
            List of ``{"job_id": int, "score": float}`` dicts sorted by
            descending score.

        Raises:
            RuntimeError: If the index has not been built or loaded.
        """
        embedding = self.embedder.encode_single(text)
        return self._search_vector(embedding, k)

    def expand(
        self,
        seed_text: str,
        rounds: int = 3,
        threshold: float = 0.7,
        top_k: int = 20,
    ) -> list[dict]:
        """Iteratively expand a seed query using document centroids.

        Each iteration:
            1. Query with the current centroid/vector.
            2. Take results above ``threshold`` and locate their source
               documents.
            3. Compute the centroid embedding from those documents.
            4. Re-query with the new centroid.

        Returns:
            Deduplicated list of results sorted by descending score.
        """
        if self._index is None:
            raise RuntimeError("Index must be built before expand")

        current_vec = self.embedder.encode_single(seed_text)
        all_results: dict[int, float] = {}

        for _ in range(rounds):
            results = self._search_vector(current_vec, top_k)
            above = [r for r in results if r["score"] >= threshold]
            if not above:
                break

            positions = [
                self._id_mapping.index(r["job_id"])
                for r in above
                if r["job_id"] in self._id_mapping
            ]
            if not positions:
                break

            centroid = self._embeddings[positions].mean(axis=0)
            centroid = _l2_normalize(centroid.reshape(1, -1))[0]
            current_vec = centroid

            for r in results:
                all_results[r["job_id"]] = max(all_results.get(r["job_id"], 0.0), r["score"])

        # Seed pass included.
        seed_results = self._search_vector(self.embedder.encode_single(seed_text), top_k)
        for r in seed_results:
            all_results[r["job_id"]] = max(all_results.get(r["job_id"], 0.0), r["score"])

        sorted_results = sorted(
            ({"job_id": jid, "score": float(score)} for jid, score in all_results.items()),
            key=lambda item: item["score"],
            reverse=True,
        )
        logger.info("Expanded query into %d unique results", len(sorted_results))
        return sorted_results

    def search_by_keywords(self, keywords: list[str], k: int = 20) -> list[dict]:
        """Query the index by averaging embeddings for ``keywords``.

        Args:
            keywords: List of keyword strings.
            k: Number of results to return.

        Returns:
            List of result dicts sorted by descending score.
        """
        if not keywords:
            return []
        embeddings = self.embedder.encode_batch(keywords, show_progress=False)
        avg = np.asarray(embeddings, dtype=np.float32).mean(axis=0)
        avg = _l2_normalize(avg.reshape(1, -1))[0]
        return self._search_vector(avg, k)

    def _search_vector(self, vector: np.ndarray, k: int) -> list[dict]:
        """Search using a raw embedding vector.

        Args:
            vector: Embedding vector (normalized).
            k: Number of results.

        Returns:
            List of ``{"job_id", "score"}`` dicts sorted by score desc.

        Raises:
            RuntimeError: If the index is not initialized.
        """
        if self._index is None:
            raise RuntimeError("SearchEngine index not built; call build_index first")

        vec = np.asarray(vector, dtype=np.float32).reshape(1, -1)
        vec = _l2_normalize(vec)
        k_eff = min(k, len(self._id_mapping))
        if k_eff <= 0:
            return []
        scores, indices = self._index.search(vec, k_eff)
        results: list[dict] = []
        for score, pos in zip(scores[0], indices[0]):
            if pos < 0 or pos >= len(self._id_mapping):
                continue
            results.append(
                {"job_id": int(self._id_mapping[int(pos)]), "score": float(score)}
            )
        results.sort(key=lambda item: item["score"], reverse=True)
        return results

    def save(self) -> None:
        """Persist the FAISS index, id mapping, and embeddings to disk."""
        import faiss

        if self._index is None:
            raise RuntimeError("Nothing to save; index not built")
        os.makedirs(os.path.dirname(self.index_path) or ".", exist_ok=True)
        os.makedirs(os.path.dirname(self.id_mapping_path) or ".", exist_ok=True)
        faiss.write_index(self._index, self.index_path)
        with open(self.id_mapping_path, "w", encoding="utf-8") as fh:
            json.dump(self._id_mapping, fh)
        if self._embeddings is not None:
            np.save(self.DEFAULT_EMBEDDINGS_PATH, self._embeddings)
        logger.info("Saved FAISS index to %s", self.index_path)

    @classmethod
    def load(
        cls,
        embedder: Embedder,
        index_path: str = DEFAULT_INDEX_PATH,
        id_mapping_path: str = DEFAULT_ID_MAPPING_PATH,
    ) -> "SearchEngine":
        """Load a SearchEngine from disk.

        Args:
            embedder: Embedder to bind.
            index_path: Path to a serialized FAISS index.
            id_mapping_path: Path to a JSON id-mapping file.

        Returns:
            A SearchEngine ready for queries.
        """
        import faiss

        instance = cls(
            embedder=embedder,
            index_path=index_path,
            id_mapping_path=id_mapping_path,
        )
        instance._index = faiss.read_index(index_path)
        with open(id_mapping_path, encoding="utf-8") as fh:
            instance._id_mapping = [int(i) for i in json.load(fh)]
        # Load the raw embedding matrix if it was saved alongside the index.
        if os.path.exists(cls.DEFAULT_EMBEDDINGS_PATH):
            try:
                instance._embeddings = np.load(cls.DEFAULT_EMBEDDINGS_PATH)
            except (OSError, ValueError):
                instance._embeddings = None
        return instance


__all__: list[str] = [
    "SearchEngine",
    "DEFAULT_INDEX_PATH",
    "DEFAULT_ID_MAPPING_PATH",
    "DEFAULT_EMBEDDINGS_PATH",
]