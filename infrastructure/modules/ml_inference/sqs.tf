resource "aws_sqs_queue" "lambda_dlq" {
  name                      = "hirenovik-lambda-dlq-${var.environment}"
  message_retention_seconds = 1209600
  receive_wait_time_seconds = 20

  tags = { Name = "hirenovik-lambda-dlq-${var.environment}", Service = "SQS" }
}

resource "aws_sqs_queue_policy" "lambda_dlq" {
  queue_url = aws_sqs_queue.lambda_dlq.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "LambdaSendMessage"
        Effect = "Allow"
        Principal = {
          AWS = aws_iam_role.lambda.arn
        }
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.lambda_dlq.arn
      }
    ]
  })
}
