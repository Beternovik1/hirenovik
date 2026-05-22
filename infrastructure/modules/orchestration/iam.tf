data "aws_iam_policy_document" "step_functions_assume_role" {
  statement {
    sid     = "StepFunctionsAssumeRole"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "step_functions" {
  name               = "hirenovik-step-functions-role-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.step_functions_assume_role.json
  tags               = { Name = "hirenovik-step-functions-role-${var.environment}", Service = "StepFunctions" }
}

data "aws_iam_policy_document" "step_functions_permissions" {
  statement {
    sid    = "GlueStartCrawler"
    effect = "Allow"
    actions = [
      "glue:StartCrawler",
      "glue:GetCrawler"
    ]
    resources = ["*"]
  }
  statement {
    sid    = "GlueStartJob"
    effect = "Allow"
    actions = [
      "glue:StartJobRun",
      "glue:GetJobRun",
      "glue:GetJobRuns",
      "glue:BatchStopJobRun"
    ]
    resources = ["*"]
  }
  statement {
    sid    = "SageMakerTraining"
    effect = "Allow"
    actions = [
      "sagemaker:CreateTrainingJob",
      "sagemaker:DescribeTrainingJob",
      "sagemaker:StopTrainingJob",
      "sagemaker:ListTags",
      "sagemaker:AddTags"
    ]
    resources = ["*"]
  }
  # Required for .sync integrations (SageMaker + Glue polling via EventBridge)
  statement {
    sid    = "EventBridgeSync"
    effect = "Allow"
    actions = [
      "events:PutTargets",
      "events:PutRule",
      "events:DescribeRule"
    ]
    resources = ["arn:aws:events:${var.region}:*:rule/StepFunctions*"]
  }
  statement {
    sid       = "PassRole"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = [var.sagemaker_role_arn]
  }
  statement {
    sid       = "SNSPublish"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [var.sns_alert_topic_arn]
  }
  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:PutLogEvents",
      "logs:CreateLogGroup",
      "logs:CreateLogStream"
    ]
    resources = ["arn:aws:logs:${var.region}:*:*"]
  }
}

resource "aws_iam_role_policy" "step_functions" {
  name   = "hirenovik-step-functions-policy-${var.environment}"
  role   = aws_iam_role.step_functions.id
  policy = data.aws_iam_policy_document.step_functions_permissions.json
}
