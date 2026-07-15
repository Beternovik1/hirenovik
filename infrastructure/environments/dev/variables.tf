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

variable "database_url" {
  description = <<-EOT
    Supabase Postgres connection string for the alert email Lambda in this
    environment. Sensitive. Set via TF_VAR_database_url or tfvars (gitignored);
    never commit a value here.
  EOT
  type        = string
  sensitive   = true
  default     = ""
}

variable "alert_recipient_email" {
  description = "Single To address for the daily digest in this environment. Set via tfvars; never commit a personal email default."
  type        = string
  default     = ""
}

variable "alert_email_dry_run" {
  description = "Initial ALERT_EMAIL_DRY_RUN on the alert email Lambda. Keep \"true\" unless this environment is cleared to send real SES traffic."
  type        = string
  default     = "true"
}

variable "alert_email_schedule_enabled" {
  description = "Whether the daily alert email schedule fires in this environment."
  type        = bool
  default     = false
}

variable "alert_email_lambda_layer_arns" {
  description = "Lambda Layer ARNs that provide runtime Python dependencies for the alert email Lambda. Required before enabling the schedule."
  type        = list(string)
  default     = []
}

variable "create_alert_email_lambda_layer" {
  description = <<-EOT
    Whether Terraform builds and publishes the alert email Lambda dependency
    layer (SQLAlchemy, psycopg2-binary, python-dotenv) in this environment.
    Defaults to true so `terraform apply` provisions a Lambda-ready layer. Set
    to false to instead supply external layer ARN(s) via
    alert_email_lambda_layer_arns. Build prerequisite: the host running
    `terraform apply` needs `pip` on PATH; pip runs at apply time only.
  EOT
  type        = bool
  default     = true
}

variable "alert_email_schedule_expression" {
  description = "EventBridge Scheduler expression for the daily alert email. Default 8:00 AM in alert_email_schedule_timezone."
  type        = string
  default     = "cron(0 8 * * ? *)"
}

variable "alert_email_schedule_timezone" {
  description = "IANA timezone for the alert email schedule expression."
  type        = string
  default     = "America/Mexico_City"
}
