import os
import tarfile
import boto3
import pandas as pd
import xgboost as xgb
import s3fs

from src.ml.training.train import FEATURE_COLUMNS

REGION = os.environ.get("AWS_REGION", "us-east-1")
MODELS_BUCKET = os.environ.get("MODELS_BUCKET", "hirenovik-models-dev")
RAW_BUCKET = os.environ.get("RAW_BUCKET", "hirenovik-raw-dev")

def main():
    print("Finding latest training data in S3...")
    fs = s3fs.S3FileSystem()
    folders = fs.ls(f"{RAW_BUCKET}/training-data/")
    if not folders:
        print("No training data found!")
        return
    latest_folder = sorted(folders)[-1]
    
    print(f"Downloading training data from {latest_folder}...")
    train_path = f"s3://{latest_folder}/train.csv"
    val_path = f"s3://{latest_folder}/validation.csv"
    
    # SageMaker CSV format: column 0 is target, no headers
    train_df = pd.read_csv(fs.open(train_path), header=None)
    val_df = pd.read_csv(fs.open(val_path), header=None)
    
    X_train = train_df.iloc[:, 1:]
    y_train = train_df.iloc[:, 0]
    
    X_val = val_df.iloc[:, 1:]
    y_val = val_df.iloc[:, 0]
    
    print("Training XGBoost model locally...")
    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=FEATURE_COLUMNS)
    dval = xgb.DMatrix(X_val, label=y_val, feature_names=FEATURE_COLUMNS)
    
    params = {
        "objective": "reg:squarederror",
        "max_depth": 6,
        "eta": 0.1,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "eval_metric": "rmse",
    }
    
    evallist = [(dtrain, 'train'), (dval, 'eval')]
    
    # Train
    bst = xgb.train(params, dtrain, num_boost_round=100, evals=evallist, early_stopping_rounds=10)
    
    # SageMaker XGBoost container expects the file to be named exactly 'xgboost-model'
    # We save as JSON explicitly because XGBoost 3.x defaults to UBJSON which might not be supported
    # by the older SageMaker containers (1.5-1 or 1.7-1).
    print("Saving model to xgboost-model.json...")
    bst.save_model("xgboost-model.json")
    os.rename("xgboost-model.json", "xgboost-model")
    
    print("Packaging into model.tar.gz...")
    with tarfile.open("model.tar.gz", "w:gz") as tar:
        tar.add("xgboost-model")
        
    s3_path = f"s3://{MODELS_BUCKET}/xgboost/model.tar.gz"
    print(f"Uploading model to {s3_path}...")
    s3 = boto3.client("s3", region_name=REGION)
    s3.upload_file("model.tar.gz", MODELS_BUCKET, "xgboost/model.tar.gz")
    
    print(f"\nModel artifact uploaded to: {s3_path}")
    print("Next step: Deploy with terraform apply -var=\"model_artifact_path=s3://hirenovik-models-dev/xgboost/model.tar.gz\"")
    
    # Cleanup
    if os.path.exists("xgboost-model"):
        os.remove("xgboost-model")
    if os.path.exists("model.tar.gz"):
        os.remove("model.tar.gz")

if __name__ == "__main__":
    main()
