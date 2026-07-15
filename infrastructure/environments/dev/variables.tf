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

variable "ses_from_email" {
  description = "Verified SES sender address (the email Source) for alert delivery. Set via tfvars; never commit a personal email here. Must be non-empty when create_ses_sender_identity is true."
  type        = string
  default     = ""
}

variable "create_ses_sender_identity" {
  description = <<-EOT
    Whether Terraform manages the SES sender identity in this environment.
    Defaults to false so `terraform apply` with no -var/tfvars cannot create
    an SES identity with an empty address. Set to true (and supply
    ses_from_email via tfvars/-var; never commit a personal email default)
    only when this environment owns the sender identity. The app SES client
    region and the `Source` passed to send_email must match this identity.
  EOT
  type        = bool
  default     = false
}
