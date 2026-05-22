# infrastructure/modules/ml_inference/variables.tf

variable "environment" {
  description = "Environment: dev or prod"
  type        = string
}

variable "curated_bucket_arn" {
  description = "ARN of the S3 curated bucket"
  type        = string
}

variable "models_bucket_name" {
  description = "Name of the S3 models bucket"
  type        = string
}

variable "models_bucket_arn" {
  description = "ARN of the S3 models bucket"
  type        = string
}

variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "model_artifact_path" {
  description = "S3 path to trained model artifact (e.g. s3://hirenovik-models-dev/xgboost/model.tar.gz)"
  type        = string
  default     = ""
}

# Serverless Inference config (replaces persistent instance vars)
variable "serverless_max_concurrency" {
  description = "Max concurrent invocations for serverless endpoint"
  type        = number
  default     = 1
}

variable "serverless_memory_size_mb" {
  description = "Memory size in MB for serverless endpoint (1024, 2048, 3072, 4096, 5120, 6144)"
  type        = number
  default     = 2048
}

variable "input_bucket_name" {
  description = "Name of the S3 input bucket for Lambda S3 trigger"
  type        = string
}

variable "input_bucket_arn" {
  description = "ARN of the S3 input bucket"
  type        = string
}

variable "raw_bucket_name" {
  description = "Name of the S3 raw bucket (for Lambda zip upload)"
  type        = string
}
