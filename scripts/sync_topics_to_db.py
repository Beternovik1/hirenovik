"""One-shot: sync topic assignments from JSON files to Supabase.

Reads topic_docs.json and topic_keywords.json, then updates the jobs
table in one SQL statement per topic (422 queries total instead of
the naive 11,639 one-per-job approach).

Usage:
    python scripts/sync_topics_to_db.py
"""

import json
import logging
import os
import sys

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from sqlalchemy import update
from sqlalchemy.orm import Session

from src.database.models import Job, db_connect

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

TOPIC_DOCS_PATH = "src/nlp/models/topic_docs.json"
TOPIC_KEYWORDS_PATH = "src/nlp/models/topic_keywords.json"


def main() -> None:
    with open(TOPIC_DOCS_PATH, encoding="utf-8") as f:
        topic_docs: dict[str, list[int]] = json.load(f)
    with open(TOPIC_KEYWORDS_PATH, encoding="utf-8") as f:
        topic_keywords: dict[str, list[str]] = json.load(f)

    total_jobs = sum(len(v) for v in topic_docs.values())
    total_topics = len(topic_docs) - 1
    logger.info(
        "Loaded %d jobs across %d topics (+ noise topic -1)",
        total_jobs, total_topics,
    )

    engine = db_connect()
    try:
        with Session(engine) as session:
            updated = 0
            for topic_id_str, job_ids in topic_docs.items():
                topic_id = int(topic_id_str)
                kw = topic_keywords.get(topic_id_str, [])
                payload = {
                    "topic_id": topic_id,
                    "topic_keywords": kw,
                }
                ids = [int(j) for j in job_ids]
                session.execute(
                    update(Job)
                    .where(Job.id.in_(ids))
                    .values(keywords_json=payload)
                )
                updated += len(ids)

            session.commit()
            logger.info("Synced %d job topic assignments to Supabase", updated)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
