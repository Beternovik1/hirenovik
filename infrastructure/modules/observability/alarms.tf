# Only create SageMaker alarm when endpoint is actually deployed
resource "aws_cloudwatch_metric_alarm" "sagemaker_error_rate" {
  count               = var.endpoint_name != "" ? 1 : 0
  alarm_name          = "hirenovik-sagemaker-error-rate-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "Invocation5XXErrors"
  namespace           = "AWS/SageMaker"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  alarm_description   = "SageMaker endpoint 5XX errors > 5 over 10 minutes"
  alarm_actions       = [var.sns_alert_topic_arn]
  ok_actions          = [var.sns_alert_topic_arn]

  dimensions = {
    EndpointName = var.endpoint_name
  }
}

resource "aws_cloudwatch_metric_alarm" "lambda_error_rate" {
  alarm_name          = "hirenovik-lambda-error-rate-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 10
  treat_missing_data  = "notBreaching"
  alarm_description   = "Lambda error rate > 10 errors over 10 minutes"
  alarm_actions       = [var.sns_alert_topic_arn]
  ok_actions          = [var.sns_alert_topic_arn]

  dimensions = {
    FunctionName = var.lambda_function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "glue_job_failure" {
  alarm_name          = "hirenovik-glue-failure-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "glue.driver.aggregate.numFailedTasks"
  namespace           = "AWS/Glue"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_description   = "Glue job has failed tasks"
  alarm_actions       = [var.sns_alert_topic_arn]

  dimensions = {
    JobName = var.glue_job_name
  }
}
