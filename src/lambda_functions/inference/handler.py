import json
import os
import traceback

import boto3

ENDPOINT_NAME = os.environ.get("ENDPOINT_NAME", "")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")
SQS_QUEUE_URL = os.environ.get("SQS_QUEUE_URL", "")

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

s3_client = boto3.client("s3")
sm_runtime = boto3.client("sagemaker-runtime")
sns_client = boto3.client("sns")
sqs_client = boto3.client("sqs")


def parse_features(job_data: dict) -> str:
    features = []
    for f in FEATURE_ORDER:
        val = job_data.get(f, 0)
        if val is None:
            val = 0
        features.append(str(val))
    return ",".join(features)


def lambda_handler(event, context):
    records = event.get("Records", [])
    if not records:
        print("No records in event")
        return {"statusCode": 400, "body": "No records"}

    for record in records:
        bucket = record["s3"]["bucket"]["name"]
        key = record["s3"]["object"]["key"]

        print(f"Processing s3://{bucket}/{key}")

        try:
            response = s3_client.get_object(Bucket=bucket, Key=key)
            job_data = json.loads(response["Body"].read().decode("utf-8"))

            features_csv = parse_features(job_data)

            sm_response = sm_runtime.invoke_endpoint(
                EndpointName=ENDPOINT_NAME,
                ContentType="text/csv",
                Body=features_csv,
            )

            prediction = sm_response["Body"].read().decode("utf-8").strip()
            print(f"Prediction: {prediction}")

            prediction_data = {
                "job_url": job_data.get("job_url", ""),
                "title": job_data.get("title", ""),
                "predicted_salary_usd": float(prediction) if prediction else 0,
            }

            sns_client.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject="Hirenovik Salary Prediction",
                Message=json.dumps(prediction_data, indent=2),
            )
            print(f"Published to SNS: {prediction_data}")

        except Exception as e:
            error_data = {
                "bucket": bucket,
                "key": key,
                "error": str(e),
                "traceback": traceback.format_exc(),
            }
            print(f"Error: {e}")

            sqs_client.send_message(
                QueueUrl=SQS_QUEUE_URL,
                MessageBody=json.dumps(error_data),
            )
            print(f"Sent error to SQS DLQ: {error_data}")

    return {"statusCode": 200, "body": "OK"}
