import argparse
import os
import subprocess
import sys
import tempfile
import time

import boto3
import pandas as pd
import s3fs

SAGEMAKER_ROLE_ARN = os.environ.get("SAGEMAKER_ROLE_ARN", "")
RAW_BUCKET = os.environ.get("RAW_BUCKET", "hirenovik-raw-dev")
CURATED_BUCKET = os.environ.get("CURATED_BUCKET", "hirenovik-curated-dev")
MODELS_BUCKET = os.environ.get("MODELS_BUCKET", "hirenovik-models-dev")
REGION = os.environ.get("AWS_REGION", "us-east-1")

KEYWORD_FEATURES = [
    "python", "aws", "spark", "docker", "sql", "tensorflow",
    "kubernetes", "airflow", "dbt", "kafka", "azure", "gcp",
    "pytorch", "scikit", "pandas", "hadoop", "snowflake",
    "bigquery", "redshift", "terraform", "jenkins", "git",
    "linux", "mlops", "databricks", "powerbi", "tableau",
    "mongodb", "postgresql", "mysql", "react", "nodejs",
    "flask", "django", "fastapi", "go", "rust", "java", "scala"
]

FEATURE_COLUMNS = [
    "seniority",
    "modality",
    "years_experience",
] + [f"has_{kw}" for kw in KEYWORD_FEATURES]

TARGET_COLUMN = "salary_mid"


def load_parquet(bucket: str) -> pd.DataFrame:
    fs = s3fs.S3FileSystem()
    s3_path = f"s3://{bucket}/jobs/"
    parquet_files = fs.glob(f"{s3_path}**/*.parquet")
    if not parquet_files:
        parquet_files = fs.glob(f"{s3_path}**/*.snappy.parquet")
    if not parquet_files:
        print("No Parquet files found.")
        sys.exit(1)
    dfs = []
    for f in parquet_files:
        with fs.open(f, "rb") as fh:
            dfs.append(pd.read_parquet(fh))
    df = pd.concat(dfs, ignore_index=True)
    print(f"Loaded {len(df)} rows from {len(parquet_files)} files")
    return df


def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    required_cols = set(FEATURE_COLUMNS + [TARGET_COLUMN])
    missing = required_cols - set(df.columns)
    if missing:
        print(f"Missing columns: {missing}")
        print("Available columns:", list(df.columns))
        sys.exit(1)

    df = df.dropna(subset=[TARGET_COLUMN])
    df = df[df[TARGET_COLUMN] > 0]

    for col in FEATURE_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    df[TARGET_COLUMN] = pd.to_numeric(df[TARGET_COLUMN], errors="coerce")

    print(f"Training rows: {len(df)}")
    print(f"Features: {len(FEATURE_COLUMNS)}")
    print(f"Target range: ${df[TARGET_COLUMN].min():.0f} - ${df[TARGET_COLUMN].max():.0f}")
    return df


def upload_training_data(df: pd.DataFrame, bucket: str, prefix: str) -> dict:
    fs = s3fs.S3FileSystem()
    train_df = df.sample(frac=0.7, random_state=42)
    remaining = df.drop(train_df.index)
    val_df = remaining.sample(frac=0.67, random_state=42)
    test_df = remaining.drop(val_df.index)

    splits = {
        "train": train_df,
        "validation": val_df,
        "test": test_df,
    }

    paths = {}
    for split_name, split_df in splits.items():
        csv_data = split_df.to_csv(
            columns=[TARGET_COLUMN] + FEATURE_COLUMNS,
            index=False,
            header=False,
        )
        s3_key = f"{prefix}/{split_name}.csv"
        s3_path = f"s3://{bucket}/{s3_key}"
        with fs.open(s3_path, "w") as fh:
            fh.write(csv_data)
        paths[split_name] = s3_path
        print(f"Uploaded {split_name}: {len(split_df)} rows -> {s3_path}")

    return paths


def launch_training_job(
    data_paths: dict,
    models_bucket: str,
    role_arn: str,
    job_name: str = "hirenovik-xgboost-training",
) -> str:
    sm = boto3.client("sagemaker", region_name=REGION)

    xgboost_container = sagemaker_image_uri(REGION, "xgboost", "1.5-1")

    training_job_name = f"{job_name}-{int(time.time())}"

    input_data_config = []
    for split_name, s3_path in data_paths.items():
        bucket_name = s3_path.split("/")[2]
        key = "/".join(s3_path.split("/")[3:])
        if split_name == "train":
            content_type = "text/csv"
            channel = "train"
        elif split_name == "validation":
            content_type = "text/csv"
            channel = "validation"
        else:
            continue

        input_data_config.append({
            "ChannelName": channel,
            "DataSource": {
                "S3DataSource": {
                    "S3DataType": "S3Prefix",
                    "S3Uri": f"s3://{bucket_name}/{os.path.dirname(key)}/",
                    "S3DataDistributionType": "FullyReplicated",
                }
            },
            "ContentType": content_type,
            "CompressionType": "None",
        })

    output_path = f"s3://{models_bucket}/xgboost/"

    print(f"Launching training job: {training_job_name}")
    print(f"Input: {input_data_config}")
    print(f"Output: {output_path}")

    sm.create_training_job(
        TrainingJobName=training_job_name,
        HyperParameters={
            "objective": "reg:squarederror",
            "num_round": "100",
            "max_depth": "6",
            "eta": "0.1",
            "subsample": "0.8",
            "colsample_bytree": "0.8",
            "gamma": "0",
            "min_child_weight": "1",
            "eval_metric": "rmse",
        },
        AlgorithmSpecification={
            "TrainingImage": xgboost_container,
            "TrainingInputMode": "File",
        },
        RoleArn=role_arn,
        InputDataConfig=input_data_config,
        OutputDataConfig={"S3OutputPath": output_path},
        ResourceConfig={
            "InstanceType": "ml.m5.large",
            "InstanceCount": 1,
            "VolumeSizeInGB": 20,
        },
        StoppingCondition={"MaxRuntimeInSeconds": 3600},
        Tags=[
            {"Key": "Project", "Value": "Hirenovik"},
            {"Key": "Environment", "Value": "dev"},
        ],
    )

    print("Waiting for training job to complete...")
    waiter = sm.get_waiter("training_job_completed_or_stopped")
    waiter.wait(TrainingJobName=training_job_name)

    desc = sm.describe_training_job(TrainingJobName=training_job_name)
    status = desc["TrainingJobStatus"]
    model_artifact = desc.get("ModelArtifacts", {}).get("S3ModelArtifacts", "N/A")
    print(f"Training job {training_job_name}: {status}")
    print(f"Model artifact: {model_artifact}")

    return model_artifact


def sagemaker_image_uri(region: str, algorithm: str, version: str) -> str:
    account_map = {
        "us-east-1": "811284229777",
        "us-east-2": "825641698319",
        "us-west-1": "632365934929",
        "us-west-2": "433757028032",
        "eu-west-1": "685385470294",
        "eu-central-1": "813361260812",
        "ap-southeast-1": "709848358524",
        "ap-northeast-1": "501404015308",
    }
    account_id = account_map.get(region, "811284229777")
    return f"{account_id}.dkr.ecr.{region}.amazonaws.com/{algorithm}:{version}"


def main():
    parser = argparse.ArgumentParser(description="Train XGBoost salary predictor on SageMaker")
    parser.add_argument("--no-train", action="store_true", help="Skip training, just prepare data")
    parser.add_argument("--job-name", default="hirenovik-xgboost-training", help="Training job name prefix")
    args = parser.parse_args()

    role_arn = SAGEMAKER_ROLE_ARN
    if not role_arn:
        print("SAGEMAKER_ROLE_ARN environment variable not set.")
        print("Usage: SAGEMAKER_ROLE_ARN=arn:aws:iam::... python train.py")
        sys.exit(1)

    print(f"Loading data from {CURATED_BUCKET}...")
    df = load_parquet(CURATED_BUCKET)

    print("Preparing features...")
    df = prepare_features(df)

    tmp_prefix = f"training-data/{int(time.time())}"
    print(f"Uploading training data to {RAW_BUCKET}/{tmp_prefix}...")
    data_paths = upload_training_data(df, RAW_BUCKET, tmp_prefix)

    if args.no_train:
        print("--no-train flag set, skipping SageMaker training")
        print(f"Data ready at: {data_paths}")
        return

    model_artifact = launch_training_job(data_paths, MODELS_BUCKET, role_arn, args.job_name)
    print(f"\nModel artifact at: {model_artifact}")
    print("\nTo deploy: update model_artifact_path in terraform and run terraform apply")


if __name__ == "__main__":
    main()
