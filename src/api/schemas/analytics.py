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
