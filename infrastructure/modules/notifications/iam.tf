# infrastructure/modules/notifications/iam.tf
#
# Least-privilege policy for sending through the configured sender identity.
# The app (src/notifications/email_sender.py) calls the SES v1 API
# `send_email` (boto3 client = "ses"), which maps to the IAM action
# `ses:SendEmail`. `ses:SendRawEmail` is intentionally omitted: the app never
# calls `send_raw_email`, so granting it would only expand the blast radius.
#
# The policy is scoped to a single sender identity ARN -- no wildcards. When
# Terraform owns the identity, the ARN comes from aws_sesv2_email_identity.
# When the identity was verified manually (current SES sandbox setup), the ARN is
# derived from region/account/email so the Lambda can still send from that single
# verified Source without importing the identity into state.

locals {
  has_ses_sender_identity = trimspace(var.ses_from_email) != ""
  ses_sender_identity_arn = var.create_ses_sender_identity ? aws_sesv2_email_identity.sender[0].arn : "arn:aws:ses:${var.region}:${data.aws_caller_identity.current.account_id}:identity/${var.ses_from_email}"
}

data "aws_iam_policy_document" "ses_send_email" {
  count = local.has_ses_sender_identity ? 1 : 0

  statement {
    sid       = "AllowSendEmailFromSenderIdentity"
    effect    = "Allow"
    actions   = ["ses:SendEmail"]
    resources = [local.ses_sender_identity_arn]
  }
}

resource "aws_iam_policy" "ses_send_email" {
  count       = var.create_ses_sender_identity ? 1 : 0
  name        = "hirenovik-ses-send-email-${var.environment}"
  description = "Least-privilege: allow ses:SendEmail only from the Terraform-managed sender identity."
  policy      = data.aws_iam_policy_document.ses_send_email[0].json

  tags = {
    Name      = "hirenovik-ses-send-email-${var.environment}"
    Layer     = "notifications"
    Component = "ses-send-policy"
  }
}
