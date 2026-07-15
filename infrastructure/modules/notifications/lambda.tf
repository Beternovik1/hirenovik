# infrastructure/modules/notifications/lambda.tf
#
# Runtime infrastructure for the daily alert email: a Lambda function that reuses
# notifications.send_digest.run_send_digest and an EventBridge Scheduler schedule
# that invokes it once a day at 8:00 AM America/Mexico_City.
#
# Architecture contract (strict scope of this slice):
#   - The Lambda only READS existing job rows from the DB, builds the digest,
#     renders HTML, and sends/dry-runs via SES. It NEVER scrapes job boards,
#     never runs enrichment, never touches Step Functions/ECS.
#   - Supabase is external and public; the Lambda uses DATABASE_URL over the
#     normal AWS network path, so no VPC configuration is attached.
#   - Dry-run remains the DEFAULT unless ALERT_EMAIL_DRY_RUN=false is set on the
#     function (see var.alert_email_dry_run). A fresh deploy with no explicit
#     override builds and logs the digest but does NOT call SES.
#   - SES send IAM is only attached when Terraform owns the sender identity
#     (var.create_ses_sender_identity). When the identity is managed outside
#     Terraform the policy ARN is empty, and we MUST NOT attach an empty/invalid
#     policy -- the count guard on the attachment enforces that.

# ---------------------------------------------------------------------------
# Package: zip the application code only (deps live in layer.tf's Lambda Layer).
# source_dir zips the whole src/ tree; `excludes` drops the heavy, unrelated
# scrapers / NLP / ETL / frontend subtrees this function never imports so the
# artifact stays small. The remaining modules (notifications, database, shared,
# lambda_functions) are the ones run_send_digest actually imports.
# ---------------------------------------------------------------------------
data "archive_file" "alert_email" {
  type        = "zip"
  source_dir  = "${path.module}/../../../src"
  output_path = "${path.module}/build/alert_email.zip"
  excludes = [
    "api",
    "data_ingestion",
    "etl",
    "glue_jobs",
    "ml",
    "nlp",
    "reporting_legacy",
    "scrapers",
    "step_functions",
    "frontend",
    "__pycache__",
    "main.py",
  ]
}

data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------------------
# Lambda execution role.
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "alert_email_lambda_assume" {
  statement {
    sid     = "AlertEmailLambdaAssumeRole"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "alert_email_lambda" {
  name               = "hirenovik-alert-email-lambda-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.alert_email_lambda_assume.json
  tags = {
    Name      = "hirenovik-alert-email-lambda-${var.environment}"
    Layer     = "notifications"
    Component = "alert-email-lambda-role"
  }
}

# CloudWatch Logs: use the AWS-managed basic-execution policy rather than
# hand-rolling logs:* statements. Keeps the least-privilege surface aligned with
# the AWS-recommended Lambda logging baseline.
resource "aws_iam_role_policy_attachment" "alert_email_logs" {
  role       = aws_iam_role.alert_email_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# SES send permission is attached ONLY when Terraform owns the sender identity
# and therefore owns the least-privilege ses:SendEmail managed policy. When
# create_ses_sender_identity is false, the policy ARN is an empty string and
# this attachment is skipped (count = 0) rather than creating an invalid
# reference. A real send in that state will fail at SES; dry-run (the default)
# never reaches SES, so safety is preserved.
resource "aws_iam_role_policy_attachment" "alert_email_ses" {
  count      = var.create_ses_sender_identity ? 1 : 0
  role       = aws_iam_role.alert_email_lambda.name
  policy_arn = aws_iam_policy.ses_send_email[0].arn
}

# ---------------------------------------------------------------------------
# Lambda function. handler points into the packaged src/ layout: at runtime
# /var/task is on sys.path, and the zip root is src/, so
# lambda_functions.alert_email.handler.lambda_handler resolves.
# ---------------------------------------------------------------------------
resource "aws_lambda_function" "alert_email" {
  function_name = "hirenovik-alert-email-${var.environment}"
  role          = aws_iam_role.alert_email_lambda.arn
  handler       = "lambda_functions.alert_email.handler.lambda_handler"
  runtime       = "python3.12"
  timeout       = var.alert_email_lambda_timeout
  memory_size   = var.alert_email_lambda_memory_size

  filename         = data.archive_file.alert_email.output_path
  source_code_hash = data.archive_file.alert_email.output_base64sha256

  # Runtime Python deps come from Lambda Layer(s). By default the Terraform-built
  # layer from layer.tf (aws_lambda_layer_version.alert_email) is attached first;
  # any ARNs in var.alert_email_lambda_layer_arns are appended for shared-lib
  # scenarios. boto3 comes from the runtime and must not be in any layer.
  # local.alert_email_effective_layers is the single source of truth also used by
  # the schedule precondition, so the two cannot drift.
  layers = local.alert_email_effective_layers

  environment {
    variables = {
      DATABASE_URL          = var.database_url
      AWS_REGION            = var.region
      SES_FROM_EMAIL        = var.ses_from_email
      ALERT_RECIPIENT_EMAIL = var.alert_recipient_email
      ALERT_EMAIL_DRY_RUN   = var.alert_email_dry_run
    }
  }

  tags = {
    Name      = "hirenovik-alert-email-${var.environment}"
    Layer     = "notifications"
    Component = "alert-email-lambda"
  }
}

# ---------------------------------------------------------------------------
# EventBridge Scheduler invocation role. The scheduler service assumes this
# role to invoke the Lambda target; it needs lambda:InvokeFunction scoped to
# this specific function ARN (no wildcard). Sentinel scheduling does NOT use a
# resource-based aws_lambda_permission -- the role's IAM permission is the
# authority, so no aws_lambda_permission resource is created here.
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "alert_email_scheduler_assume" {
  statement {
    sid     = "SchedulerAssumeRole"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "alert_email_scheduler_invoke" {
  statement {
    sid       = "InvokeAlertEmailLambda"
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.alert_email.arn]
  }
}

resource "aws_iam_role" "alert_email_scheduler" {
  name               = "hirenovik-alert-email-scheduler-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.alert_email_scheduler_assume.json
  tags = {
    Name      = "hirenovik-alert-email-scheduler-${var.environment}"
    Layer     = "notifications"
    Component = "alert-email-scheduler-role"
  }
}

resource "aws_iam_role_policy" "alert_email_scheduler_invoke" {
  name   = "hirenovik-alert-email-scheduler-invoke-${var.environment}"
  role   = aws_iam_role.alert_email_scheduler.id
  policy = data.aws_iam_policy_document.alert_email_scheduler_invoke.json
}

# ---------------------------------------------------------------------------
# Dedicated EventBridge Scheduler schedule group for this environment. The
# schedule below targets group_name implicitly via this resource so the group
# exists at apply time -- a schedule referencing a missing group fails apply.
# ---------------------------------------------------------------------------
resource "aws_scheduler_schedule_group" "alert_email" {
  name = "hirenovik-${var.environment}"

  tags = {
    Name      = "hirenovik-${var.environment}"
    Layer     = "notifications"
    Component = "alert-email-schedule-group"
  }
}

# ---------------------------------------------------------------------------
# Daily schedule. EventBridge Scheduler supports schedule_expression_timezone,
# so 8:00 AM Mexico City local time is expressed directly (no UTC math) and the
# provider handles DST. flexible_time_window OFF gives a precise 8:00 fire.
# Enablement is toggled by var.alert_email_schedule_enabled -- keep it false for
# environments that should not run unattended sends yet.
#
# Precondition: refuse to ENABLE the schedule until the operator supplies a
# runtime dependency layer. The zip packages app code only; without a layer the
# Lambda fails at import time (sqlalchemy/psycopg2/python-dotenv missing), so an
# ENABLED schedule would fire into guaranteed failures every day. A DISABLED
# schedule with no layer is allowed: that is the safe infrastructure-only state
# for a fresh apply. Do not invoke the Lambda until a dependency layer is
# attached; Python imports happen before dry-run logic can execute.
# ---------------------------------------------------------------------------
resource "aws_scheduler_schedule" "alert_email_daily" {
  name        = "hirenovik-alert-email-daily-${var.environment}"
  description = "Daily Industrial Bajio alert digest email at 8:00 AM America/Mexico_City."
  # The AWS provider exposes `state` (ENABLED/DISABLED), not `enabled`.
  group_name = aws_scheduler_schedule_group.alert_email.name

  schedule_expression          = var.alert_email_schedule_expression
  schedule_expression_timezone = var.alert_email_schedule_timezone
  state                        = var.alert_email_schedule_enabled ? "ENABLED" : "DISABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.alert_email.arn
    role_arn = aws_iam_role.alert_email_scheduler.arn
  }

  lifecycle {
    precondition {
      condition     = !var.alert_email_schedule_enabled || length(local.alert_email_effective_layers) > 0
      error_message = <<-EOT
        alert_email_schedule_enabled is true but no effective Lambda Layer is
        attached. The Terraform zip packages app code only; runtime deps
        (sqlalchemy, psycopg2-binary, python-dotenv) must come from a Lambda
        Layer. Either keep create_alert_email_lambda_layer=true (default;
        Terraform builds the layer) or supply one or more ARNs via
        alert_email_lambda_layer_arns. Enabling the unattended daily schedule
        with no layer would fire into a Lambda that fails at import time on
        every invocation. Keep alert_email_schedule_enabled=false (default;
        infrastructure-only deploy) until a layer is verified.
      EOT
    }
  }
}
