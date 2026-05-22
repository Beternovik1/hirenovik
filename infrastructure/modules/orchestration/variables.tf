# infrastructure/modules/orchestration/variables.tf

variable "environment" {
  description = "Environment: dev or prod"
  type        = string
}

variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "crawler_name" {
  description = "Name of the Glue Crawler to start"
  type        = string
}

variable "glue_job_name" {
  description = "Name of the Glue Job to run"
  type        = string
}

variable "sns_alert_topic_arn" {
  description = "ARN of the SNS topic for error alerts"
  type        = string
}

variable "training_image" {
  description = "ECR image URI for SageMaker training"
  type        = string
  default     = ""
}

variable "sagemaker_role_arn" {
  description = "ARN of the SageMaker IAM role"
  type        = string
}

variable "models_bucket_name" {
  description = "Name of the models S3 bucket"
  type        = string
}

variable "raw_bucket_name" {
  description = "Name of the raw S3 bucket (for training data)"
  type        = string
}

variable "curated_bucket_name" {
  description = "Name of the curated S3 bucket"
  type        = string
}
