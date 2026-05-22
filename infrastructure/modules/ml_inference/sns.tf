resource "aws_sns_topic" "predictions" {
  name = "hirenovik-predictions-${var.environment}"

  tags = { Name = "hirenovik-predictions-${var.environment}", Service = "SNS" }
}

resource "aws_sns_topic_policy" "predictions" {
  arn = aws_sns_topic.predictions.arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "LambdaPublish"
        Effect = "Allow"
        Principal = {
          AWS = aws_iam_role.lambda.arn
        }
        Action   = "sns:Publish"
        Resource = aws_sns_topic.predictions.arn
      }
    ]
  })
}
