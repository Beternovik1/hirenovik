# infrastructure/modules/data_engineering/outputs.tf

output "glue_database_name" {
  description = "Name of the Glue Data Catalog database"
  value       = aws_glue_catalog_database.main.name
}

output "crawler_name" {
  description = "Name of the Glue Crawler"
  value       = aws_glue_crawler.supabase_exports.name
}

output "job_name" {
  description = "Name of the Glue Job"
  value       = aws_glue_job.clean_and_curate.name
}

output "glue_role_arn" {
  description = "ARN of the Glue IAM role"
  value       = aws_iam_role.glue.arn
}
