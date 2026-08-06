"""Service layer for DB-only analytics endpoints."""

import json
import math
import re
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from statistics import median

from sqlalchemy.orm import Session

from src.api.schemas.analytics import (
    GeographyItem,
    GeographyResponse,
    IndustryDemandItem,
    IndustryDemandResponse,
    SalaryByRoleItem,
    SalaryByRoleResponse,
    SkillFrequencyItem,
    SkillFrequencyResponse,
    TimeTrendItem,
    TimeTrendResponse,
)
from src.database.models import Job

MIN_INTERPRETABLE_LISTINGS = 30
MIN_INTERPRETABLE_VALID_SALARIES = 10

ROLE_BUCKET_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "data analyst",
        re.compile(
            r"\b(data analyst|analista de datos|business intelligence|bi analyst|"
            r"power bi|analytics specialist|analytics consultant|"
            r"analista de base de datos)\b"
        ),
    ),
    (
        "data engineer",
        re.compile(
            r"\b(data engineer|ingeniero de datos|etl|data pipeline|big data|"
            r"analytics engineer|arquitecto de datos|data architect|database admin|"
            r"dba|administrador de base)\b"
        ),
    ),
    (
        "data science/ml",
        re.compile(
            r"\b(data scien|machine learning|ml engineer|ai engineer|deep learning|"
            r"nlp engineer)\b"
        ),
    ),
    (
        "software engineer",
        re.compile(
            r"\b(software engineer|software developer|ingeniero de software|"
            r"programador\b)\b"
        ),
    ),
    (
        "backend",
        re.compile(
            r"\b(backend|back end|api developer|java developer|python developer|"
            r"node developer|desarrollador python|desarrollador net|"
            r"desarrollador java|desarrollador node|net developer)\b"
        ),
    ),
    (
        "frontend",
        re.compile(
            r"\b(frontend|front end|react|angular|vue|ui developer|"
            r"desarrollador front|ux engineer)\b"
        ),
    ),
    (
        "fullstack",
        re.compile(
            r"\b(fullstack|full stack|desarrollador full|desarrollador web|"
            r"web developer)\b"
        ),
    ),
    (
        "devops/cloud",
        re.compile(
            r"\b(devops|sre|site reliability|cloud|aws|azure|kubernetes|docker|"
            r"infrastructure engineer|platform engineer|architect\b|arquitecto\b)\b"
        ),
    ),
    (
        "qa/testing",
        re.compile(
            r"\b(qa|tester|testing|test automation|quality assurance|qa engineer|"
            r"test engineer|ingeniero de pruebas)\b"
        ),
    ),
    (
        "security",
        re.compile(
            r"\b(security engineer|cyber security|cybersecurity|pentest|infosec|"
            r"security analyst)\b"
        ),
    ),
    (
        "industrial/maintenance",
        re.compile(
            r"\b(maintenance|mantenimiento|industrial|manufactur|production|plc|"
            r"calidad|quality|ingeniero electrico|ingeniero mec|"
            r"ingeniero industrial)\b"
        ),
    ),
]

ROLE_BUCKETS = [bucket for bucket, _ in ROLE_BUCKET_RULES] + ["other"]


def get_salary_by_role(db: Session) -> SalaryByRoleResponse:
    """Return role-family salary summaries derived only from the jobs table.

    Args:
        db: SQLAlchemy session.

    Returns:
        ``SalaryByRoleResponse`` with one item for each role-family bucket.
    """
    rows = db.query(Job.title, Job.salary_min, Job.salary_max).all()
    return summarize_salary_by_role(rows)


def summarize_salary_by_role(rows: Iterable[object]) -> SalaryByRoleResponse:
    """Aggregate role-family salary statistics from job-like rows.

    Args:
        rows: Iterable with ``title``, ``salary_min``, and ``salary_max`` attributes.

    Returns:
        ``SalaryByRoleResponse`` sorted by listings descending and role-family.
    """
    buckets = {bucket: _empty_bucket(bucket) for bucket in ROLE_BUCKETS}

    for row in rows:
        role_family = classify_role_family(row.title)
        bucket = buckets[role_family]
        bucket["listings"] += 1
        midpoint = _salary_midpoint(row.salary_min, row.salary_max)
        if row.salary_min is not None or row.salary_max is not None:
            bucket["salary_visible_rows"] += 1
        if midpoint is not None:
            bucket["valid_salary_rows"] += 1
            bucket["midpoints"].append(midpoint)

    items = [_build_item(bucket) for bucket in buckets.values()]
    items.sort(key=lambda item: (-item.listings, item.role_family))

    return SalaryByRoleResponse(
        items=items,
        total_listings=sum(item.listings for item in items),
        total_salary_visible_rows=sum(item.salary_visible_rows for item in items),
        total_valid_salary_rows=sum(item.valid_salary_rows for item in items),
    )


def normalize_title(title: object) -> str:
    """Normalize a title using the Notebook 3 deterministic text cleanup."""
    text = "" if title is None else str(title).casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def classify_role_family(title: object) -> str:
    """Classify a job title into the first matching role-family bucket."""
    title_norm = normalize_title(title)
    for bucket, pattern in ROLE_BUCKET_RULES:
        if pattern.search(title_norm):
            return bucket
    return "other"


def _empty_bucket(role_family: str) -> dict[str, object]:
    """Create mutable aggregate storage for one role-family bucket."""
    return {
        "role_family": role_family,
        "listings": 0,
        "salary_visible_rows": 0,
        "valid_salary_rows": 0,
        "midpoints": [],
    }


def _build_item(bucket: dict[str, object]) -> SalaryByRoleItem:
    """Convert mutable aggregate storage into an API schema."""
    listings = int(bucket["listings"])
    valid_salary_rows = int(bucket["valid_salary_rows"])
    salary_visible_rows = int(bucket["salary_visible_rows"])
    midpoints = [v for v in bucket["midpoints"] if not math.isnan(v)]
    salary_visibility_rate = salary_visible_rows / listings if listings else 0.0

    return SalaryByRoleItem(
        role_family=str(bucket["role_family"]),
        listings=listings,
        salary_visible_rows=salary_visible_rows,
        valid_salary_rows=valid_salary_rows,
        median_salary_midpoint=median(midpoints) if midpoints else None,
        min_salary_midpoint=min(midpoints) if midpoints else None,
        max_salary_midpoint=max(midpoints) if midpoints else None,
        salary_visibility_rate=salary_visibility_rate,
        interpretation_ready=(
            listings >= MIN_INTERPRETABLE_LISTINGS
            and valid_salary_rows >= MIN_INTERPRETABLE_VALID_SALARIES
        ),
    )


def _salary_midpoint(salary_min: object, salary_max: object) -> float | None:
    """Return the midpoint for valid salary pairs, otherwise None."""
    if salary_min is None or salary_max is None:
        return None

    minimum = _to_float(salary_min)
    maximum = _to_float(salary_max)
    if math.isnan(minimum) or math.isnan(maximum):
        return None
    if minimum < 1 or maximum < 1 or minimum > maximum:
        return None
    return (minimum + maximum) / 2


def _to_float(value: object) -> float:
    """Convert SQL numeric values into floats for JSON-safe summaries."""
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def get_industry_demand(db: Session) -> IndustryDemandResponse:
    """Return industry demand summaries grouped by niche, career, type, and site.

    Args:
        db: SQLAlchemy session.

    Returns:
        ``IndustryDemandResponse`` with one item per group combination.
    """
    rows = db.query(
        Job.title,
        Job.salary_min,
        Job.salary_max,
        Job.industry_niche,
        Job.career,
        Job.job_type,
        Job.site,
        Job.date_scraped,
        Job.date_posted,
    ).all()
    return summarize_industry_demand(rows)


def summarize_industry_demand(
    rows: Iterable[object],
) -> IndustryDemandResponse:
    """Aggregate industry demand statistics from job-like rows.

    Args:
        rows: Iterable with ``title``, ``salary_min``, ``salary_max``,
            ``industry_niche``, ``career``, ``job_type``, ``site``,
            ``date_scraped``, and ``date_posted`` attributes.

    Returns:
        ``IndustryDemandResponse`` sorted by listings descending and group columns.
    """
    groups: dict[tuple[str, str, str, str], dict[str, object]] = {}

    for row in rows:
        key = (
            row.industry_niche or "Unknown",
            row.career or "Unknown",
            row.job_type or "Unknown",
            row.site or "Unknown",
        )
        if key not in groups:
            groups[key] = {
                "industry_niche": key[0],
                "career": key[1],
                "job_type": key[2],
                "site": key[3],
                "listings": 0,
                "salary_visible_rows": 0,
                "valid_salary_rows": 0,
                "midpoints": [],
                "dates_scraped": [],
                "dates_posted": [],
            }

        bucket = groups[key]
        bucket["listings"] += 1
        midpoint = _salary_midpoint(row.salary_min, row.salary_max)
        if row.salary_min is not None or row.salary_max is not None:
            bucket["salary_visible_rows"] += 1
        if midpoint is not None:
            bucket["valid_salary_rows"] += 1
            bucket["midpoints"].append(midpoint)
        if row.date_scraped is not None:
            bucket["dates_scraped"].append(_to_iso(row.date_scraped))
        if row.date_posted is not None:
            bucket["dates_posted"].append(str(row.date_posted))

    items = [_build_industry_item(bucket) for bucket in groups.values()]
    items.sort(
        key=lambda item: (
            -item.listings,
            item.industry_niche or "",
            item.career or "",
            item.job_type or "",
            item.site or "",
        ),
    )

    return IndustryDemandResponse(
        items=items,
        total_listings=sum(item.listings for item in items),
        total_salary_visible_rows=sum(item.salary_visible_rows for item in items),
        total_valid_salary_rows=sum(item.valid_salary_rows for item in items),
        total_groups=len(items),
    )


def _build_industry_item(bucket: dict[str, object]) -> IndustryDemandItem:
    """Convert mutable aggregate storage into an API schema."""
    listings = int(bucket["listings"])
    valid_salary_rows = int(bucket["valid_salary_rows"])
    salary_visible_rows = int(bucket["salary_visible_rows"])
    midpoints = [v for v in bucket["midpoints"] if not math.isnan(v)]
    dates_scraped = bucket["dates_scraped"]
    dates_posted = bucket["dates_posted"]
    salary_visibility_rate = salary_visible_rows / listings if listings else 0.0

    return IndustryDemandItem(
        industry_niche=str(bucket["industry_niche"]),
        career=str(bucket["career"]),
        job_type=str(bucket["job_type"]),
        site=str(bucket["site"]),
        listings=listings,
        salary_visible_rows=salary_visible_rows,
        valid_salary_rows=valid_salary_rows,
        median_salary_midpoint=median(midpoints) if midpoints else None,
        salary_visibility_rate=salary_visibility_rate,
        first_date_scraped=min(dates_scraped) if dates_scraped else None,
        last_date_scraped=max(dates_scraped) if dates_scraped else None,
        first_date_posted=min(dates_posted) if dates_posted else None,
        last_date_posted=max(dates_posted) if dates_posted else None,
        interpretation_ready=(
            listings >= MIN_INTERPRETABLE_LISTINGS
            and valid_salary_rows >= MIN_INTERPRETABLE_VALID_SALARIES
        ),
    )


def _to_iso(dt: datetime) -> str:
    """Convert a datetime to an ISO 8601 string."""
    return dt.isoformat()


def get_geography(db: Session) -> GeographyResponse:
    """Return geography summaries grouped by country, state, and raw_location.

    Args:
        db: SQLAlchemy session.

    Returns:
        ``GeographyResponse`` with one item for each location group.
    """
    rows = db.query(
        Job.title,
        Job.salary_min,
        Job.salary_max,
        Job.country,
        Job.state,
        Job.raw_location,
    ).all()
    return summarize_geography(rows)


def summarize_geography(rows: Iterable[object]) -> GeographyResponse:
    """Aggregate geography statistics from job-like rows.

    Args:
        rows: Iterable with ``title``, ``salary_min``, ``salary_max``,
            ``country``, ``state``, and ``raw_location`` attributes.

    Returns:
        ``GeographyResponse`` sorted by listings descending, then country,
        state, and raw_location ascending.
    """
    groups: dict[tuple[str, str, str], dict[str, object]] = {}

    for row in rows:
        key = (
            row.country or "Unknown",
            row.state or "Unknown",
            row.raw_location or "Unknown",
        )
        if key not in groups:
            groups[key] = {
                "country": key[0],
                "state": key[1],
                "raw_location": key[2],
                "listings": 0,
                "salary_visible_rows": 0,
                "valid_salary_rows": 0,
                "midpoints": [],
            }

        bucket = groups[key]
        bucket["listings"] += 1
        midpoint = _salary_midpoint(row.salary_min, row.salary_max)
        if row.salary_min is not None or row.salary_max is not None:
            bucket["salary_visible_rows"] += 1
        if midpoint is not None:
            bucket["valid_salary_rows"] += 1
            bucket["midpoints"].append(midpoint)

    items = [_build_geography_item(bucket) for bucket in groups.values()]
    items.sort(
        key=lambda item: (
            -item.listings,
            item.country or "",
            item.state or "",
            item.raw_location or "",
        ),
    )

    return GeographyResponse(
        items=items,
        total_listings=sum(item.listings for item in items),
        total_salary_visible_rows=sum(item.salary_visible_rows for item in items),
        total_valid_salary_rows=sum(item.valid_salary_rows for item in items),
        total_locations=len(items),
    )


def _build_geography_item(bucket: dict[str, object]) -> GeographyItem:
    """Convert mutable aggregate storage into an API schema."""
    listings = int(bucket["listings"])
    valid_salary_rows = int(bucket["valid_salary_rows"])
    salary_visible_rows = int(bucket["salary_visible_rows"])
    midpoints = [v for v in bucket["midpoints"] if not math.isnan(v)]
    salary_visibility_rate = salary_visible_rows / listings if listings else 0.0

    return GeographyItem(
        country=str(bucket["country"]),
        state=str(bucket["state"]),
        raw_location=str(bucket["raw_location"]),
        listings=listings,
        salary_visible_rows=salary_visible_rows,
        valid_salary_rows=valid_salary_rows,
        median_salary_midpoint=median(midpoints) if midpoints else None,
        min_salary_midpoint=min(midpoints) if midpoints else None,
        max_salary_midpoint=max(midpoints) if midpoints else None,
        salary_visibility_rate=salary_visibility_rate,
        interpretation_ready=(
            listings >= MIN_INTERPRETABLE_LISTINGS
            and valid_salary_rows >= MIN_INTERPRETABLE_VALID_SALARIES
        ),
    )


def get_skill_frequency(db: Session, limit: int = 50) -> SkillFrequencyResponse:
    """Return global keyword frequency from the keywords_json column.

    Args:
        db: SQLAlchemy session.
        limit: Maximum number of keywords to return (default 50, max 200).

    Returns:
        ``SkillFrequencyResponse`` with items sorted by count descending,
        then keyword ascending.
    """
    rows = db.query(
        Job.id,
        Job.title,
        Job.salary_min,
        Job.salary_max,
        Job.keywords_json,
    ).all()
    return summarize_skill_frequency(rows, limit=limit)


def summarize_skill_frequency(
    rows: Iterable[object],
    limit: int = 50,
) -> SkillFrequencyResponse:
    """Aggregate global keyword frequency from job-like rows.

    Args:
        rows: Iterable with ``id``, ``title``, ``salary_min``,
            ``salary_max``, and ``keywords_json`` attributes.
        limit: Maximum number of keywords to include in the response.

    Returns:
        ``SkillFrequencyResponse`` sorted by count descending, keyword
        ascending, limited to ``limit`` items.
    """
    keyword_to_job_ids: dict[str, set[int]] = {}
    total_listings = 0
    total_listings_with_keywords = 0

    for row in rows:
        total_listings += 1
        keywords = _parse_keywords(row.keywords_json)
        if not keywords:
            continue
        total_listings_with_keywords += 1
        for kw in keywords:
            if kw not in keyword_to_job_ids:
                keyword_to_job_ids[kw] = set()
            keyword_to_job_ids[kw].add(row.id)

    keyword_coverage_pct = (
        round(total_listings_with_keywords / total_listings * 100, 1)
        if total_listings > 0
        else 0.0
    )

    items = [
        SkillFrequencyItem(keyword=kw, rows=len(job_ids))
        for kw, job_ids in keyword_to_job_ids.items()
    ]
    items.sort(key=lambda item: (-item.rows, item.keyword))
    items = items[:limit]

    return SkillFrequencyResponse(
        items=items,
        total_unique_keywords=len(keyword_to_job_ids),
        total_listings_with_keywords=total_listings_with_keywords,
        total_listings=total_listings,
        keyword_coverage_pct=keyword_coverage_pct,
    )


def get_time_trends(db: Session, granularity: str) -> TimeTrendResponse:
    """Return time-series trends grouped by week or month.

    Args:
        db: SQLAlchemy session.
        granularity: Grouping granularity, either ``"week"`` or ``"month"``.

    Returns:
        ``TimeTrendResponse`` with one item per period sorted
        chronologically.
    """
    rows = db.query(
        Job.title,
        Job.salary_min,
        Job.salary_max,
        Job.date_scraped,
        Job.date_posted,
    ).all()
    return summarize_time_trends(rows, granularity)


def summarize_time_trends(
    rows: Iterable[object],
    granularity: str,
) -> TimeTrendResponse:
    """Aggregate time-series statistics from job-like rows.

    Args:
        rows: Iterable with ``title``, ``salary_min``, ``salary_max``,
            ``date_scraped``, and ``date_posted`` attributes.
        granularity: Grouping granularity, either ``"week"`` or ``"month"``.

    Returns:
        ``TimeTrendResponse`` sorted by ``period_start`` ascending.
    """
    periods: dict[tuple, dict[str, object]] = {}

    for row in rows:
        if row.date_scraped is None:
            continue

        key = _period_key(row.date_scraped, granularity)
        if key not in periods:
            periods[key] = {
                "period_start": _period_start(key, granularity),
                "listings": 0,
                "salary_visible_rows": 0,
                "valid_salary_rows": 0,
                "midpoints": [],
                "date_posted_count": 0,
            }

        bucket = periods[key]
        bucket["listings"] += 1
        midpoint = _salary_midpoint(row.salary_min, row.salary_max)
        if row.salary_min is not None or row.salary_max is not None:
            bucket["salary_visible_rows"] += 1
        if midpoint is not None:
            bucket["valid_salary_rows"] += 1
            bucket["midpoints"].append(midpoint)
        if row.date_posted is not None:
            bucket["date_posted_count"] += 1

    items = sorted(
        [_build_time_trend_item(bucket) for bucket in periods.values()],
        key=lambda item: item.period_start,
    )

    return TimeTrendResponse(
        items=items,
        total_listings=sum(item.listings for item in items),
        total_salary_visible_rows=sum(item.salary_visible_rows for item in items),
        total_valid_salary_rows=sum(item.valid_salary_rows for item in items),
        period_count=len(items),
    )


def _period_key(dt: datetime, granularity: str) -> tuple:
    """Return a sortable grouping key for the given datetime and granularity."""
    if granularity == "week":
        iso = dt.isocalendar()
        return (iso[0], iso[1])
    return (dt.year, dt.month)


def _period_start(key: tuple, granularity: str) -> str:
    """Return the ISO 8601 date string for the first day of a period."""
    if granularity == "week":
        return datetime.fromisocalendar(key[0], key[1], 1).date().isoformat()
    return date(key[0], key[1], 1).isoformat()


def _build_time_trend_item(bucket: dict[str, object]) -> TimeTrendItem:
    """Convert mutable aggregate storage into an API schema."""
    listings = int(bucket["listings"])
    valid_salary_rows = int(bucket["valid_salary_rows"])
    salary_visible_rows = int(bucket["salary_visible_rows"])
    midpoints = [v for v in bucket["midpoints"] if not math.isnan(v)]
    date_posted_count = int(bucket["date_posted_count"])

    return TimeTrendItem(
        period_start=str(bucket["period_start"]),
        listings=listings,
        salary_visible_rows=salary_visible_rows,
        valid_salary_rows=valid_salary_rows,
        median_salary_midpoint=median(midpoints) if midpoints else None,
        date_posted_listings=date_posted_count if date_posted_count else None,
    )


def _parse_keywords(keywords_json: object) -> list[str]:
    """Safely parse keywords_json into a normalized list of strings.

    Handles None, already-parsed lists, JSON strings, and empty values.
    Empty or invalid input returns an empty list.
    """
    if keywords_json is None:
        return []
    if isinstance(keywords_json, list):
        return [
            str(kw).strip().casefold()
            for kw in keywords_json
            if kw is not None and str(kw).strip()
        ]
    if isinstance(keywords_json, str):
        try:
            parsed = json.loads(keywords_json)
            if isinstance(parsed, list):
                return [
                    str(kw).strip().casefold()
                    for kw in parsed
                    if kw is not None and str(kw).strip()
                ]
        except json.JSONDecodeError:
            return []
    return []
