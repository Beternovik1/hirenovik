# infrastructure/modules/notifications/variables.tf

variable "environment" {
  description = "Environment: dev or prod"
  type        = string
}

variable "region" {
  description = "AWS region for the SES identity and IAM policy resources."
  type        = string
  default     = "us-east-1"
}

variable "ses_from_email" {
  description = <<-EOT
    Verified SES sender address (the email "Source"). This module manages the
    identity for this address. Never hardcode a personal address in defaults;
    provide it via tfvars or -var at apply time. Must be non-empty when
    create_ses_sender_identity is true.
  EOT
  type        = string
}

variable "create_ses_sender_identity" {
  description = <<-EOT
    Whether Terraform owns the SES sender identity (and its least-privilege
    IAM policy). Defaults to false so an accidental `terraform apply` with no
    -var/tfvars cannot create an SES identity with an empty address: creation
    is opt-in and explicit. When false, no SES identity and no managed policy
    are created, and the identity/policy outputs return empty strings. Set to
    true only when `ses_from_email` is also supplied, and the sender identity
    is owned by Terraform; set to false when the identity is managed outside
    Terraform and the send policy will be attached elsewhere with the
    external identity ARN.
  EOT
  type        = bool
  default     = false
}

# ---------------------------------------------------------------------------
# Alert email Lambda + schedule variables.
# Never commit secrets or personal email defaults -- supply these via tfvars /
# -var / TF_VAR_* at apply time. database_url is sensitive.
# ---------------------------------------------------------------------------

variable "database_url" {
  description = <<-EOT
    Supabase Postgres connection string for the alert email Lambda. Sensitive.
    The Lambda reads this and passes it to database.models.db_connect. Supply
    via TF_VAR_database_url or tfvars (gitignored); never commit a value.
  EOT
  type        = string
  sensitive   = true
  default     = ""
}

variable "alert_recipient_email" {
  description = <<-EOT
    Single To address for the daily digest. Owned by config/env, NOT by
    Terraform subscribers -- there is no subscriber database in this slice.
    Provide via tfvars or -var; never commit a personal email default.
  EOT
  type        = string
  default     = ""
}

variable "alert_email_dry_run" {
  description = <<-EOT
    Initial value of ALERT_EMAIL_DRY_RUN on the Lambda. Keep "true" (the safe
    default) for environments not ready to send real SES traffic. Accepted
    tokens: "true","1","yes","on" / "false","0","no","off" (case-insensitive).
    The app's resolve_dry_run fails closed on any other value.
  EOT
  type        = string
  default     = "true"
}

variable "alert_email_schedule_enabled" {
  description = <<-EOT
    Whether the daily EventBridge Scheduler schedule fires (ENABLED/DISABLED).
    Defaults to false so a fresh `terraform apply` with no overrides cannot
    enable unattended daily sends: the schedule is created in DISABLED state
    and the operator flips this to true only after the Lambda layer (runtime
    deps) and SES sender identity are verified. Enabling the schedule without
    supplying alert_email_lambda_layer_arns fails plan (see the precondition on
    aws_scheduler_schedule.alert_email_daily): the zip packages app code only,
    so an enabled schedule with no layer would fire into a Lambda that fails at
    import time on every invocation.
  EOT
  type        = bool
  default     = false
}

# ---------------------------------------------------------------------------
# Runtime dependency layer. The Terraform zip packages application code only;
# Python runtime deps (sqlalchemy, psycopg2-binary, python-dotenv) are NOT
# bundled. Provide one or more Lambda Layer ARN(s) here that supply those
# packages. The list is attached as `layers` on aws_lambda_function.alert_email.
# Defaulting to an empty list keeps `terraform apply` safe as infrastructure-only;
# the Lambda is not invokable until dependencies are supplied. The schedule
# precondition blocks enabling unattended sends until at least one layer is
# supplied.
# ---------------------------------------------------------------------------

variable "alert_email_lambda_layer_arns" {
  description = <<-EOT
    Optional list of Lambda Layer ARN(s) providing the alert email Lambda's
    runtime Python deps (sqlalchemy, psycopg2-binary, python-dotenv). boto3 is
    supplied by the Lambda runtime and must NOT be included. The Terraform zip
    packages app code only. Leave empty for an infrastructure-only deploy; the
    Lambda is not invokable until dependencies are layered. The daily schedule's
    precondition refuses to be ENABLED until a layer is supplied, so unattended
    invocations cannot fire into a Lambda that would fail at import time.
  EOT
  type        = list(string)
  default     = []
}

variable "alert_email_schedule_expression" {
  description = <<-EOT
    Schedule expression for the daily alert email. Default fires once a day.
    Combined with alert_email_schedule_timezone, the default cron(0 8 * * ? *)
    means 8:00 AM local. Use a valid EventBridge Scheduler rate/cron expression.
  EOT
  type        = string
  default     = "cron(0 8 * * ? *)"
}

variable "alert_email_schedule_timezone" {
  description = <<-EOT
    IANA timezone for the schedule expression (EventBridge Scheduler). Default
    America/Mexico_City expresses the 8:00 AM cron directly in local time; the
    provider handles DST, so no UTC conversion is required.
  EOT
  type        = string
  default     = "America/Mexico_City"
}

variable "alert_email_lambda_timeout" {
  description = "Timeout in seconds for the alert email Lambda."
  type        = number
  default     = 60
}

variable "alert_email_lambda_memory_size" {
  description = "Memory (MB) for the alert email Lambda."
  type        = number
  default     = 256
}
