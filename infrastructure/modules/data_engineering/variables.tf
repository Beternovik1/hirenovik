# infrastructure/modules/data_engineering/variables.tf

variable "environment" {
  description = "Environment: dev or prod"
  type        = string
}

variable "raw_bucket_name" {
  description = "Name of the S3 raw bucket"
  type        = string
}

variable "raw_bucket_arn" {
  description = "ARN of the S3 raw bucket"
  type        = string
}

variable "curated_bucket_name" {
  description = "Name of the S3 curated bucket"
  type        = string
}

variable "curated_bucket_arn" {
  description = "ARN of the S3 curated bucket"
  type        = string
}

variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}
