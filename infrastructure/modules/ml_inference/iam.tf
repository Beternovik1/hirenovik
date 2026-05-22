# infrastructure/modules/iam.tf

data "aws_iam_policy_document" "sagemaker_assume_role" {
  statement {
    sid     = "SageMakerAssumeRole"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["sagemaker.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sagemaker" {
  name               = "hirenovik-sagemaker-role-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.sagemaker_assume_role.json
  tags               = { Name = "hirenovik-sagemaker-role-${var.environment}", Service = "SageMaker" }
}

data "aws_iam_policy_document" "sagemaker_permissions" {
  statement {
    sid    = "S3ReadCurated"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:ListBucket"
    ]
    resources = [
      var.curated_bucket_arn,
      "${var.curated_bucket_arn}/*"
    ]
  }
  statement {
    sid    = "S3ReadWriteModels"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:ListBucket"
    ]
    resources = [
      var.models_bucket_arn,
      "${var.models_bucket_arn}/*"
    ]
  }
  statement {
    sid    = "SageMakerFull"
    effect = "Allow"
    actions = [
      "sagemaker:CreateModel",
      "sagemaker:DeleteModel",
      "sagemaker:DescribeModel",
      "sagemaker:CreateEndpointConfig",
      "sagemaker:DeleteEndpointConfig",
      "sagemaker:DescribeEndpointConfig",
      "sagemaker:CreateEndpoint",
      "sagemaker:DeleteEndpoint",
      "sagemaker:DescribeEndpoint",
      "sagemaker:InvokeEndpoint",
      "sagemaker:CreateTrainingJob",
      "sagemaker:DescribeTrainingJob",
      "sagemaker:StopTrainingJob",
      "sagemaker:ListTags"
    ]
    resources = ["*"]
  }
  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:PutLogEvents",
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams"
    ]
    resources = ["arn:aws:logs:${var.region}:*:*"]
  }
  statement {
    sid       = "PassRole"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["sagemaker.amazonaws.com"]
    }
  }
  statement {
    sid       = "EC2Describe"
    effect    = "Allow"
    actions   = ["ec2:DescribeVpcEndpoints"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "sagemaker" {
  name   = "hirenovik-sagemaker-policy-${var.environment}"
  role   = aws_iam_role.sagemaker.id
  policy = data.aws_iam_policy_document.sagemaker_permissions.json
}
