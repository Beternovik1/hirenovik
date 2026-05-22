# infrastructure/modules/ml_inference/lambda.tf

data "archive_file" "lambda_handler" {
  type        = "zip"
  source_file = "${path.module}/../../../src/lambda_functions/inference/handler.py"
  output_path = "${path.module}/build/lambda_handler.zip"
}

resource "aws_s3_object" "lambda_handler" {
  bucket = var.raw_bucket_name
  key    = "lambda/handler.zip"
  source = data.archive_file.lambda_handler.output_path
  etag   = data.archive_file.lambda_handler.output_base64sha256
}

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    sid     = "LambdaAssumeRole"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "hirenovik-lambda-role-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags               = { Name = "hirenovik-lambda-role-${var.environment}", Service = "Lambda" }
}

data "aws_iam_policy_document" "lambda_permissions" {
  statement {
    sid    = "S3ReadInput"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:ListBucket"
    ]
    resources = [
      var.input_bucket_arn,
      "${var.input_bucket_arn}/*"
    ]
  }
  statement {
    sid    = "SageMakerInvoke"
    effect = "Allow"
    actions = [
      "sagemaker:InvokeEndpoint"
    ]
    # Scoped to hirenovik endpoints in this account/region, not wildcard
    resources = ["arn:aws:sagemaker:${var.region}:${data.aws_caller_identity.current.account_id}:endpoint/hirenovik-*"]
  }
  statement {
    sid       = "SNSPublish"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.predictions.arn]
  }
  statement {
    sid       = "SQSSend"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.lambda_dlq.arn]
  }
  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = ["arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:*"]
  }
  statement {
    sid    = "XRay"
    effect = "Allow"
    actions = [
      "xray:PutTraceSegments",
      "xray:PutTelemetryRecords"
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "hirenovik-lambda-policy-${var.environment}"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda_permissions.json
}

resource "aws_lambda_function" "inference" {
  function_name = "hirenovik-inference-${var.environment}"
  role          = aws_iam_role.lambda.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.12"
  timeout       = 30
  memory_size   = 128

  s3_bucket = var.raw_bucket_name
  s3_key    = aws_s3_object.lambda_handler.key

  environment {
    variables = {
      ENDPOINT_NAME = try(aws_sagemaker_endpoint.salary_predictor[0].name, "")
      SNS_TOPIC_ARN = aws_sns_topic.predictions.arn
      SQS_QUEUE_URL = aws_sqs_queue.lambda_dlq.url
    }
  }

  tracing_config {
    mode = "PassThrough"
  }

  tags = { Name = "hirenovik-inference-${var.environment}", Service = "Lambda" }
}

resource "aws_lambda_permission" "s3_invoke" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.inference.arn
  principal     = "s3.amazonaws.com"
  source_arn    = var.input_bucket_arn
}

resource "aws_s3_bucket_notification" "input_trigger" {
  bucket = var.input_bucket_name

  lambda_function {
    lambda_function_arn = aws_lambda_function.inference.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = ""
    filter_suffix       = ".json"
  }

  depends_on = [aws_lambda_permission.s3_invoke]
}
