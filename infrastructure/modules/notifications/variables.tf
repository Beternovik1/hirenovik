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