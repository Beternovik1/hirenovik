output "dashboard_name" {
  description = "Name of the CloudWatch dashboard"
  value       = aws_cloudwatch_dashboard.main.dashboard_name
}

output "sagemaker_alarm_name" {
  description = "Name of the SageMaker error rate alarm"
  value       = try(aws_cloudwatch_metric_alarm.sagemaker_error_rate[0].alarm_name, "")
}

output "lambda_alarm_name" {
  description = "Name of the Lambda error rate alarm"
  value       = aws_cloudwatch_metric_alarm.lambda_error_rate.alarm_name
}

output "glue_alarm_name" {
  description = "Name of the Glue job failure alarm"
  value       = aws_cloudwatch_metric_alarm.glue_job_failure.alarm_name
}
