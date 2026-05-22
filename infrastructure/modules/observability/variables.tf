# infrastructure/modules/observability/variables.tf

variable "environment" {
  description = "Environment: dev or prod"
  type        = string
}

variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "curated_bucket_name" {
  description = "Name of the curated S3 bucket"
  type        = string
}

variable "endpoint_name" {
  description = "Name of the SageMaker endpoint"
  type        = string
}

variable "lambda_function_name" {
  description = "Name of the inference Lambda function"
  type        = string
}

variable "sns_alert_topic_arn" {
  description = "ARN of the SNS topic for alarm notifications"
  type        = string
}

variable "glue_job_name" {
  description = "Name of the Glue job"
  type        = string
}

variable "state_machine_arn" {
  description = "ARN of the Step Functions state machine"
  type        = string
}
