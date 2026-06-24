"""One-shot: sync topic assignments from JSON files to Supabase.

Reads topic_docs.json (topic_id → job_ids) and topic_keywords.json
(topic_id → keywords) and updates the keywords_json column in the
jobs table for every job. Run this after retraining the topic model.

Usage:
    python scripts/sync_topics_to_db.py
"""

import json
import logging
import sys

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
    total_topics = len(topic_docs) - 1  # exclude -1
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
                for job_id in job_ids:
                    session.execute(
                        update(Job)
                        .where(Job.id == int(job_id))
                        .values(keywords_json=payload)
                    )
                    updated += 1

                if updated % 500 == 0:
                    session.commit()
                    logger.info("Committed %d updates ...", updated)

            session.commit()
            logger.info("Synced %d job topic assignments to Supabase", updated)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
