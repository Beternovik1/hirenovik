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
# When the sender identity was verified manually (current SES sandbox setup), the
# ARN is derived from region/account/email so the Lambda can still send from that
# single verified Source without importing the identity into state. SES sandbox
# can also authorize against the verified recipient identity, so the current
# one-recipient MVP includes the configured recipient ARN when present. Future
# production access should remove recipient-scoped IAM and keep subscribers in
# the database, not Terraform.

locals {
  has_ses_sender_identity    = trimspace(var.ses_from_email) != ""
  has_ses_recipient_identity = trimspace(var.alert_recipient_email) != ""
  ses_sender_identity_arn    = var.create_ses_sender_identity ? aws_sesv2_email_identity.sender[0].arn : "arn:aws:ses:${var.region}:${data.aws_caller_identity.current.account_id}:identity/${var.ses_from_email}"
  ses_recipient_identity_arns = local.has_ses_recipient_identity ? [
    "arn:aws:ses:${var.region}:${data.aws_caller_identity.current.account_id}:identity/${var.alert_recipient_email}"
  ] : []
  ses_send_identity_arns = concat([local.ses_sender_identity_arn], local.ses_recipient_identity_arns)
}

data "aws_iam_policy_document" "ses_send_email" {
  count = local.has_ses_sender_identity ? 1 : 0

  statement {
    sid       = "AllowSendEmailFromSenderIdentity"
    effect    = "Allow"
    actions   = ["ses:SendEmail"]
    resources = local.ses_send_identity_arns
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
