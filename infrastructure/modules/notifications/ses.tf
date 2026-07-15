# infrastructure/modules/notifications/ses.tf
#
# Terraform owns the SES sender identity only. Recipients are owned by the
# app/env (ALERT_RECIPIENT_EMAIL), and future subscriber emails belong in the
# database -- never here. No recipient identity is created: SES sandbox lets a
# verified sender deliver to any other verified address in the same account,
# and prod moves out of sandbox via AWS support, so a recipient identity
# resource is not needed for this slice.
#
# Region / Source alignment: SES identities are regional. The app's SES client
# (boto3 `ses`) MUST target the same AWS region as `var.region` here, and the
# `Source` passed to `send_email` in src/notifications/email_sender.py MUST
# equal `var.ses_from_email`. A mismatch (different region or a different
# Source address) makes ses:SendEmail reject with MES000 / 400 even though the
# IAM policy and identity look fine. Keep region + Source coupled.

# SES v2 email identity. The AWS provider (~> 6.0) exposes sesv2 resources, and
# this is the modern, preferred resource for verified addresses. Creating an
# email-address identity causes SES to send a verification email to that
# address; the identity is unusable until the recipient clicks the link. See
# "Manual steps" in the change notes.
#
# Creation is opt-in (create_ses_sender_identity defaults to false). The
# precondition below is defense-in-depth: even if someone flips the flag on
# without supplying an address, the plan fails loudly instead of submitting
# aws_sesv2_email_identity with an empty email_identity.
resource "aws_sesv2_email_identity" "sender" {
  count          = var.create_ses_sender_identity ? 1 : 0
  email_identity = var.ses_from_email

  lifecycle {
    precondition {
      condition     = var.ses_from_email != ""
      error_message = "ses_from_email must be a non-empty sender address when create_ses_sender_identity is true. Provide it via tfvars or -var (never commit a personal email default); the app SES region and Source must match this identity."
    }
  }

  tags = {
    Name      = "hirenovik-ses-sender-${var.environment}"
    Layer     = "notifications"
    Component = "ses-sender-identity"
  }
}