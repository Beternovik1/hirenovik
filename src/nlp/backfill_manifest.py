"""Operational audit manifest for backfill runs.

Generates JSON artifacts recording exactly which job IDs were affected
by a single controlled run. Used for targeted rollback and auditing.

Manifests are NOT API data, NOT stored in the database, and NOT
consumed by the frontend. They are local operational artifacts.

Usage::

    from src.nlp.backfill_manifest import BackfillManifest

    manifest = BackfillManifest(
        run_type="description_preparer",
        command="python -m src.nlp.description_preparer --limit 1000",
        version="1.0.0",
        limit=1000,
    )
    manifest.add_batch([1, 2, 3])
    manifest.add_batch([4, 5, 6])
    manifest.save()

    # Rollback: read the manifest, UPDATE only those IDs
    manifest = BackfillManifest.load("artifacts/backfills/description-preparer-2026-08-07T120000.json")
    print(manifest.affected_ids)  # → [1, 2, 3, 4, 5, 6]
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

#: Directory where manifest artifacts are stored.  Not committed to Git.
DEFAULT_ARTIFACTS_DIR = Path("artifacts/backfills")


class BackfillManifest:
    """Record of job IDs affected by one backfill run.

    Attributes:
        run_type: e.g. ``"description_preparer"``, ``"skill_enricher"``.
        command: Exact CLI command executed.
        version: Extractor or preparer version string.
        limit: The ``--limit`` value used, or ``None``.
        source: The ``--source`` filter, or ``None``.
        started_at: ISO 8601 UTC timestamp.
        affected_ids: Ordered list of job IDs modified.
        metadata: Arbitrary extra data (e.g. metrics summary).
    """

    def __init__(
        self,
        run_type: str,
        command: str,
        version: str,
        limit: Optional[int] = None,
        source: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        self.run_type = run_type
        self.command = command
        self.version = version
        self.limit = limit
        self.source = source
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.affected_ids: list[int] = []
        self.metadata = metadata or {}

    def add_batch(self, ids: list[int]) -> None:
        """Record a batch of affected job IDs."""
        self.affected_ids.extend(ids)

    def save(self, directory: Optional[Path] = None) -> Path:
        """Persist the manifest to disk.

        Args:
            directory: Output directory.  Defaults to
                ``artifacts/backfills/``.

        Returns:
            Path to the written manifest file.
        """
        out_dir = directory or DEFAULT_ARTIFACTS_DIR
        out_dir.mkdir(parents=True, exist_ok=True)

        timestamp = self.started_at.replace(":", "").replace("+", "Z")[:19]
        filename = f"{self.run_type}-{timestamp}.json"
        path = out_dir / filename

        payload = {
            "run_type": self.run_type,
            "command": self.command,
            "version": self.version,
            "limit": self.limit,
            "source": self.source,
            "started_at": self.started_at,
            "affected_count": len(self.affected_ids),
            "affected_ids": self.affected_ids,
            "metadata": self.metadata,
        }

        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, path: Path) -> "BackfillManifest":
        """Load a previously-saved manifest.

        Args:
            path: Path to the manifest JSON file.

        Returns:
            A :class:`BackfillManifest` with ``affected_ids`` populated.
        """
        data = json.loads(path.read_text(encoding="utf-8"))
        m = cls(
            run_type=data["run_type"],
            command=data["command"],
            version=data["version"],
            limit=data.get("limit"),
            source=data.get("source"),
            metadata=data.get("metadata", {}),
        )
        m.started_at = data["started_at"]
        m.affected_ids = data["affected_ids"]
        return m

    def rollback_sql(self) -> str:
        """Return a targeted rollback UPDATE statement.

        Only affects the exact IDs in this manifest — never a broad
        ``WHERE version = ...`` clause.
        """
        if not self.affected_ids:
            return "-- No IDs to rollback."

        id_list = ", ".join(str(i) for i in self.affected_ids)

        if self.run_type == "description_preparer":
            return (
                f"UPDATE jobs SET cleaned_description = NULL, "
                f"description_enrichment_source = NULL "
                f"WHERE id IN ({id_list});"
            )
        elif self.run_type == "skill_enricher":
            return (
                f"UPDATE jobs SET skills_json = NULL, "
                f"skill_extractor_version = NULL, "
                f"skills_extracted_at = NULL "
                f"WHERE id IN ({id_list});"
            )
        else:
            return f"-- Unknown run_type '{self.run_type}'; rollback manually for IDs: {id_list}"
