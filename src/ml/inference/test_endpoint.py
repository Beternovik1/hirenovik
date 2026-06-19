import argparse
import json
import os

import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
ENDPOINT_NAME = os.environ.get("ENDPOINT_NAME", "")

SAMPLE_JOBS = [
    {
        "title": "Data Engineer Senior",
        "seniority": 3,
        "modality": 0,
        "years_experience": 6,
        "has_python": 1, "has_aws": 1, "has_spark": 1, "has_docker": 1,
        "has_sql": 1, "has_airflow": 1, "has_kafka": 0, "has_kubernetes": 0,
        "has_tensorflow": 0, "has_dbt": 1, "has_azure": 0, "has_gcp": 0,
        "has_pytorch": 0, "has_pandas": 1, "has_hadoop": 0, "has_snowflake": 1,
        "has_bigquery": 0, "has_redshift": 1, "has_terraform": 1, "has_jenkins": 0,
        "has_git": 1, "has_linux": 1, "has_mlops": 0, "has_databricks": 1,
        "has_powerbi": 0, "has_tableau": 0, "has_mongodb": 0, "has_postgresql": 1,
        "has_mysql": 0, "has_react": 0, "has_nodejs": 0, "has_flask": 0,
        "has_django": 0, "has_fastapi": 0, "has_go": 0, "has_rust": 0,
        "has_java": 0, "has_scala": 0,
    },
    {
        "title": "Data Analyst Junior",
        "seniority": 0,
        "modality": 1,
        "years_experience": 0,
        "has_python": 1, "has_aws": 0, "has_spark": 0, "has_docker": 0,
        "has_sql": 1, "has_airflow": 0, "has_kafka": 0, "has_kubernetes": 0,
        "has_tensorflow": 0, "has_dbt": 0, "has_azure": 0, "has_gcp": 0,
        "has_pytorch": 0, "has_pandas": 1, "has_hadoop": 0, "has_snowflake": 0,
        "has_bigquery": 1, "has_redshift": 0, "has_terraform": 0, "has_jenkins": 0,
        "has_git": 0, "has_linux": 0, "has_mlops": 0, "has_databricks": 0,
        "has_powerbi": 1, "has_tableau": 1, "has_mongodb": 0, "has_postgresql": 0,
        "has_mysql": 1, "has_react": 0, "has_nodejs": 0, "has_flask": 0,
        "has_django": 0, "has_fastapi": 0, "has_go": 0, "has_rust": 0,
        "has_java": 0, "has_scala": 0,
    },
    {
        "title": "Cloud Engineer Semi-Senior",
        "seniority": 2,
        "modality": 0,
        "years_experience": 4,
        "has_python": 1, "has_aws": 1, "has_spark": 0, "has_docker": 1,
        "has_sql": 0, "has_airflow": 0, "has_kafka": 0, "has_kubernetes": 1,
        "has_tensorflow": 0, "has_dbt": 0, "has_azure": 1, "has_gcp": 1,
        "has_pytorch": 0, "has_pandas": 0, "has_hadoop": 0, "has_snowflake": 0,
        "has_bigquery": 0, "has_redshift": 0, "has_terraform": 1, "has_jenkins": 1,
        "has_git": 1, "has_linux": 1, "has_mlops": 1, "has_databricks": 0,
        "has_powerbi": 0, "has_tableau": 0, "has_mongodb": 0, "has_postgresql": 0,
        "has_mysql": 0, "has_react": 0, "has_nodejs": 0, "has_flask": 0,
        "has_django": 0, "has_fastapi": 0, "has_go": 1, "has_rust": 0,
        "has_java": 0, "has_scala": 0,
    },
    {
        "title": "Data Scientist",
        "seniority": 2,           
        "modality": 0,            
        "years_experience": 3,
        "has_python": 1, "has_tensorflow": 1, "has_sql": 1, "has_pandas": 1,
    }
]

FEATURE_ORDER = [
    "seniority", "modality", "years_experience",
    "has_python", "has_aws", "has_spark", "has_docker",
    "has_sql", "has_airflow", "has_kafka", "has_kubernetes",
    "has_tensorflow", "has_dbt", "has_azure", "has_gcp",
    "has_pytorch", "has_pandas", "has_hadoop", "has_snowflake",
    "has_bigquery", "has_redshift", "has_terraform", "has_jenkins",
    "has_git", "has_linux", "has_mlops", "has_databricks",
    "has_powerbi", "has_tableau", "has_mongodb", "has_postgresql",
    "has_mysql", "has_react", "has_nodejs", "has_flask",
    "has_django", "has_fastapi", "has_go", "has_rust",
    "has_java", "has_scala",
]


def parse_args():
    parser = argparse.ArgumentParser(description="Test SageMaker endpoint")
    parser.add_argument("--endpoint", default=ENDPOINT_NAME, help="Endpoint name")
    parser.add_argument("--job-index", type=int, default=0, help="Sample job index (0-2)")
    return parser.parse_args()


def main():
    args = parse_args()
    endpoint = args.endpoint
    if not endpoint:
        print("ENDPOINT_NAME not set and --endpoint not provided")
        print("Usage: ENDPOINT_NAME=hirenovik-salary-endpoint-dev python test_endpoint.py")
        return

    job = SAMPLE_JOBS[args.job_index]
    features = [str(job.get(f, 0)) for f in FEATURE_ORDER]
    payload = ",".join(features)

    print(f"Endpoint: {endpoint}")
    print(f"Job: {job['title']}")
    print(f"Features: {payload}")

    sm_runtime = boto3.client("sagemaker-runtime", region_name=REGION)
    response = sm_runtime.invoke_endpoint(
        EndpointName=endpoint,
        ContentType="text/csv",
        Body=payload,
    )

    result = response["Body"].read().decode("utf-8").strip()
    try:
        prediction = float(result)
        print(f"\nPredicted salary: ${prediction:,.0f} USD/month (approx. ${prediction * 12:,.0f} USD/year)")
    except ValueError:
        print(f"\nRaw response: {result}")

    print(f"\nSample job details:")
    print(f"  Title: {job['title']}")
    print(f"  Seniority: {job['seniority']}")
    print(f"  Modality: {job['modality']}")
    print(f"  Years exp: {job['years_experience']}")
    skills = [k.replace("has_", "") for k, v in job.items() if k.startswith("has_") and v]
    print(f"  Skills: {', '.join(skills)}")


if __name__ == "__main__":
    main()
