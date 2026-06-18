locals {
  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 8
        height = 6
        properties = {
          view    = "timeSeries"
          stacked = false
          metrics = [
            ["Glue", "glue.driver.aggregate.elapsedTime", "JobName", var.glue_job_name, "Type", "gauge", { stat = "Maximum", label = "Elapsed Time" }]
          ]
          region = var.region
          title  = "Glue Job Duration"
          period = 86400
          yAxis  = { left = { label = "Milliseconds" } }
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 0
        width  = 8
        height = 6
        properties = {
          view = "singleValue"
          metrics = [
            ["AWS/S3", "NumberOfObjects", "BucketName", var.curated_bucket_name, "StorageType", "AllStorageTypes", { stat = "Average" }]
          ]
          region = var.region
          title  = "Files in Curated Zone"
          period = 86400
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 0
        width  = 8
        height = 6
        properties = {
          view    = "singleValue"
          stacked = false
          metrics = [
            ["AWS/SageMaker", "Invocation5XXErrors", "EndpointName", var.endpoint_name != "" ? var.endpoint_name : "hirenovik-salary-endpoint-dev", { stat = "Sum" }]
          ]
          region = var.region
          title  = "Endpoint Error Rate"
          period = 300
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 8
        height = 6
        properties = {
          view    = "timeSeries"
          stacked = false
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", var.lambda_function_name, { stat = "Average", label = "Avg Duration" }],
            ["AWS/Lambda", "Errors", "FunctionName", var.lambda_function_name, { stat = "Sum", label = "Errors" }]
          ]
          region = var.region
          title  = "Lambda Inference"
          period = 300
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 6
        width  = 8
        height = 6
        properties = {
          view    = "singleValue"
          stacked = false
          metrics = [
            ["AWS/States", "ExecutionsFailed", "StateMachineArn", var.state_machine_arn, { stat = "Sum", label = "Failed" }],
            ["AWS/States", "ExecutionsSucceeded", "StateMachineArn", var.state_machine_arn, { stat = "Sum", label = "Succeeded" }]
          ]
          region = var.region
          title  = "Pipeline Executions"
          period = 86400
        }
      }
    ]
  })
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "hirenovik-${var.environment}"
  dashboard_body = local.dashboard_body
}