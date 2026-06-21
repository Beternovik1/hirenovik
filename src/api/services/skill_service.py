"""Service layer for skill extraction from text.

Detects technology keywords in job descriptions using word-boundary regex.
The keyword list matches the 39 features used in the XGBoost model so that
extracted skills are consistent with the ML training data.
"""

import logging
import re
from typing import Optional

from src.api.schemas.skill import SkillExtractionResponse

logger = logging.getLogger(__name__)

#: Technology keywords used in the XGBoost model feature engineering.
#: Each keyword maps to a word-boundary regex pattern for matching.
KEYWORD_FEATURES: list[str] = [
    "python", "aws", "spark", "docker", "sql", "tensorflow",
    "kubernetes", "airflow", "dbt", "kafka", "azure", "gcp",
    "pytorch", "scikit", "pandas", "hadoop", "snowflake",
    "bigquery", "redshift", "terraform", "jenkins", "git",
    "linux", "mlops", "databricks", "powerbi", "tableau",
    "mongodb", "postgresql", "mysql", "react", "nodejs",
    "flask", "django", "fastapi", "go", "rust", "java", "scala",
]

#: Pre-compiled regex patterns for efficient matching.
_KEYWORD_PATTERNS: dict[str, re.Pattern] = {
    kw: re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE) for kw in KEYWORD_FEATURES
}


def extract_skills(text: str) -> SkillExtractionResponse:
    """Extract technology keywords from text using word-boundary matching.

    Args:
        text: Job description or other text to scan for skills.

    Returns:
        ``SkillExtractionResponse`` with matched skills and count.
    """
    found: list[str] = []
    for keyword, pattern in _KEYWORD_PATTERNS.items():
        if pattern.search(text):
            found.append(keyword)
    return SkillExtractionResponse(skills=found, count=len(found))