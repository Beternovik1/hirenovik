# infrastructure/modules/notifications/iam.tf
#
# Least-privilege policy for sending through the Terraform-managed sender
# identity. The app (src/notifications/email_sender.py) calls the SES v1 API
# `send_email` (boto3 client = "ses"), which maps to the IAM action
# `ses:SendEmail`. `ses:SendRawEmail` is intentionally omitted: the app never
# calls `send_raw_email`, so granting it would only expand the blast radius.
#
# The policy is scoped to the sender identity ARN
# (arn:aws:ses:<region>:<account>:identity/<email>) exported by
# aws_sesv2_email_identity -- no wildcards. A managed IAM policy is created
# (rather than only emitting JSON) so a future Lambda/ECS role can attach it
# by ARN via aws_iam_role_policy_attachment. The policy is created together
# with the identity: if Terraform does not own the identity, it also does not
# own a send policy for it (manage the external ARN elsewhere instead).

data "aws_iam_policy_document" "ses_send_email" {
  count = var.create_ses_sender_identity ? 1 : 0

  statement {
    sid       = "AllowSendEmailFromSenderIdentity"
    effect    = "Allow"
    actions   = ["ses:SendEmail"]
    resources = [aws_sesv2_email_identity.sender[0].arn]
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