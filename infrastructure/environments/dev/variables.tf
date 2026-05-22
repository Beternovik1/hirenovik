variable "aws_region" {
  default = "us-east-1"
}

variable "environment" {
  default = "dev"
}

variable "model_artifact_path" {
  description = "S3 path to trained XGBoost model artifact. Set after training completes."
  type        = string
  default     = ""
}
