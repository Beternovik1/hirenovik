import sys
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, row_number, when, coalesce, lit, count as spark_count
from pyspark.sql.window import Window
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions

args = getResolvedOptions(sys.argv, ["JOB_NAME", "raw_bucket", "curated_bucket"])
spark = SparkSession.builder.config("spark.sql.sources.partitionOverwriteMode", "dynamic").getOrCreate()
glue_context = GlueContext(spark.sparkContext)
job = Job(glue_context)
job.init(args["JOB_NAME"], args)

raw_bucket = args["raw_bucket"]
curated_bucket = args["curated_bucket"]

raw_path = f"s3://{raw_bucket}/supabase_exports/"
output_path = f"s3://{curated_bucket}/jobs/"

# Solo lee las carpetas particionadas (ingestion_date=*), ignora checkpoint/ y archivos sueltos
read_path = f"s3://{raw_bucket}/supabase_exports/ingestion_date=*/"

df = spark.read.option("header", "true").option("inferSchema", "true").option("basePath", raw_path).csv(read_path)

# ---------------------------------------------------------------------------
# Deduplicación
# ---------------------------------------------------------------------------
df = df.dropDuplicates(["job_url"])

window_spec = Window.partitionBy("job_url").orderBy(col("date_scraped").desc())
df = df.withColumn("rn", row_number().over(window_spec)).filter(col("rn") == 1).drop("rn")

# ---------------------------------------------------------------------------
# Feature Engineering — Salarios
# ---------------------------------------------------------------------------
df = df.withColumn(
    "salary_mid",
    (coalesce(col("salary_min"), lit(0)) + coalesce(col("salary_max"), lit(0))) / 2
)

df = df.withColumn(
    "salary_mid_usd",
    when(col("currency") == "MXN", col("salary_mid") / 17.5).otherwise(col("salary_mid"))
)

df = df.withColumn(
    "has_salary",
    when(col("salary_min").isNotNull() & col("salary_max").isNotNull(), lit(True)).otherwise(lit(False))
)

# Filtra outliers — salarios imposibles
df = df.filter(
    ~col("has_salary") |  # conserva los sin salario
    (
        (col("salary_mid") >= 5000) &
        (col("salary_mid") <= 150000) &
        (col("currency") == "MXN")
    )
)

# ---------------------------------------------------------------------------
# Feature Engineering — Seniority, Experience, Modality
# ---------------------------------------------------------------------------
df = df.withColumn(
    "seniority",
    when(col("title").rlike("(?i)(^|\\s)(semi-senior|mid|intermediate|ssr)(\\s|$)"), 2)
    .when(col("title").rlike("(?i)(^|\\s)(senior|sr\\.?|lead|principal|staff)(\\s|$)"), 3)
    .when(col("title").rlike("(?i)(^|\\s)(junior|jr\\.?|trainee|entry)(\\s|$)"), 0)
    .otherwise(1)
)

df = df.withColumn(
    "years_experience",
    when(col("seniority") == 3, 6)
    .when(col("seniority") == 2, 4)
    .when(col("seniority") == 1, 2)
    .when(col("seniority") == 0, 0)
    .otherwise(1)
)

df = df.withColumn(
    "modality",
    when(col("job_type") == "remoto", 0)
    .when(col("job_type") == "hibrido", 1)
    .when(col("job_type") == "presencial", 2)
    .otherwise(1)
)

# ---------------------------------------------------------------------------
# Feature Engineering — Keywords en descripción
# ---------------------------------------------------------------------------
keyword_features = [
    "python", "aws", "spark", "docker", "sql", "tensorflow",
    "kubernetes", "airflow", "dbt", "kafka", "azure", "gcp",
    "pytorch", "scikit", "pandas", "hadoop", "snowflake",
    "bigquery", "redshift", "terraform", "jenkins", "git",
    "linux", "mlops", "databricks", "powerbi", "tableau",
    "mongodb", "postgresql", "mysql", "react", "nodejs",
    "flask", "django", "fastapi", "go", "rust", "java", "scala"
]

for kw in keyword_features:
    df = df.withColumn(
        f"has_{kw}",
        when(col("description").rlike(f"(?i)\\b{kw}\\b"), lit(1)).otherwise(lit(0))
    )

# ---------------------------------------------------------------------------
# Filtro de carreras con pocos datos (para entrenamiento ML)
# ---------------------------------------------------------------------------
career_counts = df.filter(col("has_salary") == True)\
                  .groupBy("career")\
                  .agg(spark_count("*").alias("cnt"))

valid_careers = career_counts.filter(col("cnt") >= 30).select("career")

df = df.withColumn(
    "is_valid_for_training",
    when(
        col("has_salary") & col("career").isin(
            [r["career"] for r in valid_careers.collect()]
        ),
        lit(True)
    ).otherwise(lit(False))
)

# ---------------------------------------------------------------------------
# Selección final de columnas y escritura a Parquet
# ---------------------------------------------------------------------------
select_cols = [
    "job_url", "title", "company", "site", "country", "state",
    "career", "job_type", "modality", "seniority", "years_experience",
    "salary_min", "salary_max", "currency", "salary_mid", "salary_mid_usd",
    "has_salary", "is_valid_for_training",
    "date_posted", "date_scraped", "status",
    "raw_location", "ingestion_date"
] + [f"has_{kw}" for kw in keyword_features]

existing_cols = [c for c in select_cols if c in df.columns]
df = df.select(*existing_cols)

df.write.mode("overwrite").partitionBy("ingestion_date").parquet(output_path)

job.commit()
