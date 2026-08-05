"""Pydantic schemas for analytics API responses."""

from pydantic import BaseModel


class SalaryByRoleItem(BaseModel):
    """Salary summary for one deterministic role-family bucket."""

    role_family: str
    listings: int
    salary_visible_rows: int
    valid_salary_rows: int
    median_salary_midpoint: float | None = None
    min_salary_midpoint: float | None = None
    max_salary_midpoint: float | None = None
    salary_visibility_rate: float
    interpretation_ready: bool


class SalaryByRoleResponse(BaseModel):
    """Role-family salary summary with dataset-level totals."""

    items: list[SalaryByRoleItem]
    total_listings: int
    total_salary_visible_rows: int
    total_valid_salary_rows: int


class IndustryDemandItem(BaseModel):
    """Salary demand summary for one industry-niche/career/job-type/site group."""

    industry_niche: str | None = None
    career: str | None = None
    job_type: str | None = None
    site: str | None = None
    listings: int
    salary_visible_rows: int
    valid_salary_rows: int
    median_salary_midpoint: float | None = None
    salary_visibility_rate: float
    first_date_scraped: str | None = None
    last_date_scraped: str | None = None
    first_date_posted: str | None = None
    last_date_posted: str | None = None
    interpretation_ready: bool


class IndustryDemandResponse(BaseModel):
    """Industry demand summary with dataset-level totals."""

    items: list[IndustryDemandItem]
    total_listings: int
    total_salary_visible_rows: int
    total_valid_salary_rows: int
    total_groups: int


class GeographyItem(BaseModel):
    """Salary summary for one (country, state, raw_location) group."""

    country: str | None = None
    state: str | None = None
    raw_location: str | None = None
    listings: int
    salary_visible_rows: int
    valid_salary_rows: int
    median_salary_midpoint: float | None = None
    min_salary_midpoint: float | None = None
    max_salary_midpoint: float | None = None
    salary_visibility_rate: float
    interpretation_ready: bool


class GeographyResponse(BaseModel):
    """Geography salary summary with dataset-level totals."""

    items: list[GeographyItem]
    total_listings: int
    total_salary_visible_rows: int
    total_valid_salary_rows: int
    total_locations: int


class SkillFrequencyItem(BaseModel):
    """Keyword frequency for one skill extracted from keywords_json."""

    keyword: str
    rows: int


class SkillFrequencyResponse(BaseModel):
    """Global keyword frequency with dataset-level metadata."""

    items: list[SkillFrequencyItem]
    total_unique_keywords: int
    total_listings_with_keywords: int


class TimeTrendItem(BaseModel):
    """Time-series data point for one grouping period."""

    period_start: str
    listings: int
    salary_visible_rows: int
    valid_salary_rows: int
    median_salary_midpoint: float | None = None
    date_posted_listings: int | None = None


class TimeTrendResponse(BaseModel):
    """Time-series trends with dataset-level metadata."""

    items: list[TimeTrendItem]
    total_listings: int
    total_salary_visible_rows: int
    total_valid_salary_rows: int
    period_count: int
