locals {
  dashboard_body = jsonencode({
    widgets = [
      # Widget 1 (REQUIRED): Glue Job duration over time — line chart
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
      # Widget 2 (REQUIRED): Files in Curated Zone — counter
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
      # Widget 3 (REQUIRED): SageMaker endpoint error rate — metric
      {
        type   = "metric"
        x      = 16
        y      = 0
        width  = 8
        height = 6
        properties = {
          view    = "timeSeries"
          stacked = false
          metrics = [
            ["AWS/SageMaker/Endpoints", "Invocation5XXErrors", "EndpointName", var.endpoint_name, "VariantName", "primary", { stat = "Sum", label = "5XX Errors", id = "m1" }],
            ["AWS/SageMaker/Endpoints", "Invocations", "EndpointName", var.endpoint_name, "VariantName", "primary", { stat = "Sum", label = "Invocations", id = "m2" }],
            [{ expression = "IF(m2>0, m1/m2*100, 0)", label = "Error Rate %", id = "e1", yAxis = "right" }]
          ]
          region = var.region
          title  = "SageMaker Endpoint Error Rate"
          period = 300
          yAxis  = { left = { label = "Count" }, right = { label = "%" } }
        }
      },
      # BONUS: Lambda inference duration
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
      # BONUS: Step Functions executions
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
