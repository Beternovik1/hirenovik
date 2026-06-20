"""Pydantic schemas for salary prediction API requests and responses."""

from pydantic import BaseModel, Field

#: The 39 keyword features used in the XGBoost model, in training order.
KEYWORD_FEATURES: list[str] = [
    "python", "aws", "spark", "docker", "sql", "tensorflow",
    "kubernetes", "airflow", "dbt", "kafka", "azure", "gcp",
    "pytorch", "scikit", "pandas", "hadoop", "snowflake",
    "bigquery", "redshift", "terraform", "jenkins", "git",
    "linux", "mlops", "databricks", "powerbi", "tableau",
    "mongodb", "postgresql", "mysql", "react", "nodejs",
    "flask", "django", "fastapi", "go", "rust", "java", "scala",
]


class SalaryFeatures(BaseModel):
    """Feature vector for XGBoost salary prediction.

    Accepts a skills list instead of 39 individual has_* flags. The
    service layer converts the skills list into the binary feature
    vector required by the model.
    """

    seniority: int = Field(
        default=1, ge=0, le=3,
        description="0=junior, 1=mid, 2=semi-senior, 3=senior",
    )
    modality: int = Field(
        default=2, ge=0, le=2,
        description="0=remoto, 1=hibrido, 2=presencial",
    )
    years_experience: int = Field(
        default=2, ge=0, le=6,
        description="Mapped from seniority: 0=junior, 2=mid, 4=semi-senior, 6=senior",
    )
    skills: list[str] = Field(
        default_factory=list,
        description="Technology skills (e.g. python, aws, docker). Unknown skills are ignored.",
    )


class SalaryPrediction(BaseModel):
    """XGBoost salary prediction response."""

    predicted_salary_mid_mxn: float
    currency: str = "MXN"
    features_used: dict