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

    The 41 features match the training data column order exactly:
    seniority (0-3), modality (0-2), years_experience (0-6),
    then 39 binary keyword flags.
    """

    seniority: int = Field(
        default=1, ge=0, le=3,
        description="0=junior, 1=semi-senior, 2=semi-senior, 3=senior",
    )
    modality: int = Field(
        default=2, ge=0, le=2,
        description="0=remoto, 1=hibrido, 2=presencial",
    )
    years_experience: int = Field(
        default=2, ge=0, le=6,
        description="Mapped from seniority: 0=junior, 2=semi, 4=ssr, 6=senior",
    )
    has_python: int = Field(default=0, ge=0, le=1)
    has_aws: int = Field(default=0, ge=0, le=1)
    has_spark: int = Field(default=0, ge=0, le=1)
    has_docker: int = Field(default=0, ge=0, le=1)
    has_sql: int = Field(default=0, ge=0, le=1)
    has_tensorflow: int = Field(default=0, ge=0, le=1)
    has_airflow: int = Field(default=0, ge=0, le=1)
    has_kafka: int = Field(default=0, ge=0, le=1)
    has_kubernetes: int = Field(default=0, ge=0, le=1)
    has_dbt: int = Field(default=0, ge=0, le=1)
    has_azure: int = Field(default=0, ge=0, le=1)
    has_gcp: int = Field(default=0, ge=0, le=1)
    has_pytorch: int = Field(default=0, ge=0, le=1)
    has_scikit: int = Field(default=0, ge=0, le=1)
    has_pandas: int = Field(default=0, ge=0, le=1)
    has_hadoop: int = Field(default=0, ge=0, le=1)
    has_snowflake: int = Field(default=0, ge=0, le=1)
    has_bigquery: int = Field(default=0, ge=0, le=1)
    has_redshift: int = Field(default=0, ge=0, le=1)
    has_terraform: int = Field(default=0, ge=0, le=1)
    has_jenkins: int = Field(default=0, ge=0, le=1)
    has_git: int = Field(default=0, ge=0, le=1)
    has_linux: int = Field(default=0, ge=0, le=1)
    has_mlops: int = Field(default=0, ge=0, le=1)
    has_databricks: int = Field(default=0, ge=0, le=1)
    has_powerbi: int = Field(default=0, ge=0, le=1)
    has_tableau: int = Field(default=0, ge=0, le=1)
    has_mongodb: int = Field(default=0, ge=0, le=1)
    has_postgresql: int = Field(default=0, ge=0, le=1)
    has_mysql: int = Field(default=0, ge=0, le=1)
    has_react: int = Field(default=0, ge=0, le=1)
    has_nodejs: int = Field(default=0, ge=0, le=1)
    has_flask: int = Field(default=0, ge=0, le=1)
    has_django: int = Field(default=0, ge=0, le=1)
    has_fastapi: int = Field(default=0, ge=0, le=1)
    has_go: int = Field(default=0, ge=0, le=1)
    has_rust: int = Field(default=0, ge=0, le=1)
    has_java: int = Field(default=0, ge=0, le=1)
    has_scala: int = Field(default=0, ge=0, le=1)


class SalaryPrediction(BaseModel):
    """XGBoost salary prediction response."""

    predicted_salary_mid_mxn: float
    currency: str = "MXN"
    features_used: dict