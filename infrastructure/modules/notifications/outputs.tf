# infrastructure/modules/notifications/outputs.tf
#
# Surfaces for future Lambda/ECS integration:
#   - ses_sender_email:           the Source address the app passes to SES.
#   - ses_sender_identity_arn:    scopes any hand-rolled policy to this identity.
#   - ses_send_email_policy_arn:  attach to a Lambda/ECS execution role by ARN.
#   - ses_send_email_policy_json: inline equivalent if a managed policy is not
#                                 desired.
#
# When create_ses_sender_identity is false, the identity/policy outputs are
# empty strings and the email output still reflects the configured address.

output "ses_sender_email" {
  description = "Configured SES sender (Source) email address."
  value       = var.ses_from_email
}

output "ses_sender_identity_arn" {
  description = "ARN of the Terraform-managed SES sender identity; empty when not created by Terraform."
  value       = var.create_ses_sender_identity ? aws_sesv2_email_identity.sender[0].arn : ""
}

output "ses_send_email_policy_arn" {
  description = "ARN of the least-privilege ses:SendEmail managed policy; empty when not created by Terraform."
  value       = var.create_ses_sender_identity ? aws_iam_policy.ses_send_email[0].arn : ""
}

output "ses_send_email_policy_json" {
  description = "JSON of the least-privilege ses:SendEmail policy document; empty when not created by Terraform."
  value       = var.create_ses_sender_identity ? data.aws_iam_policy_document.ses_send_email[0].json : ""
}