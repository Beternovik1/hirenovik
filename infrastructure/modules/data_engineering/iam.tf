# infrastructure/modules/data_engineering/iam.tf

data "aws_iam_policy_document" "glue_assume_role" {
  statement {
    sid     = "GlueServiceAssumeRole"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "glue" {
  name               = "hirenovik-glue-role-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.glue_assume_role.json
  tags               = { Name = "hirenovik-glue-role-${var.environment}", Service = "Glue" }
}

data "aws_iam_policy_document" "glue_permissions" {
  statement {
    sid    = "S3ReadRaw"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:ListBucket"
    ]
    resources = [
      var.raw_bucket_arn,
      "${var.raw_bucket_arn}/*"
    ]
  }
  statement {
    sid    = "S3WriteCurated"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:ListBucket"
    ]
    resources = [
      var.curated_bucket_arn,
      "${var.curated_bucket_arn}/*"
    ]
  }
  statement {
    sid    = "GlueFull"
    effect = "Allow"
    actions = [
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:CreateTable",
      "glue:GetTable",
      "glue:GetTables",
      "glue:UpdateTable",
      "glue:DeleteTable",
      "glue:BatchCreatePartition",
      "glue:GetPartition",
      "glue:GetPartitions",
      "glue:BatchGetPartition"
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
    sid    = "PassRole"
    effect = "Allow"
    actions = [
      "iam:PassRole"
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["glue.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "glue" {
  name   = "hirenovik-glue-policy-${var.environment}"
  role   = aws_iam_role.glue.id
  policy = data.aws_iam_policy_document.glue_permissions.json
}
