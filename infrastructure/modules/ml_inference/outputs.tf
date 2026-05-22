# infrastructure/modules/ml_inference/outputs.tf

output "endpoint_name" {
  description = "Name of the SageMaker endpoint"
  value       = try(aws_sagemaker_endpoint.salary_predictor[0].name, "")
}

output "endpoint_arn" {
  description = "ARN of the SageMaker endpoint"
  value       = try(aws_sagemaker_endpoint.salary_predictor[0].arn, "")
}

output "model_name" {
  description = "Name of the SageMaker model"
  value       = try(aws_sagemaker_model.salary_predictor[0].name, "")
}

output "sagemaker_role_arn" {
  description = "ARN of the SageMaker IAM role"
  value       = aws_iam_role.sagemaker.arn
}

output "sns_topic_arn" {
  description = "ARN of the SNS predictions topic"
  value       = aws_sns_topic.predictions.arn
}

output "sqs_queue_url" {
  description = "URL of the SQS DLQ"
  value       = aws_sqs_queue.lambda_dlq.url
}

output "sqs_queue_arn" {
  description = "ARN of the SQS DLQ"
  value       = aws_sqs_queue.lambda_dlq.arn
}

output "lambda_function_name" {
  description = "Name of the inference Lambda function"
  value       = aws_lambda_function.inference.function_name
}

output "lambda_role_arn" {
  description = "ARN of the Lambda IAM role"
  value       = aws_iam_role.lambda.arn
}

output "training_image_uri" {
  description = "ECR image URI for XGBoost training"
  value       = data.aws_sagemaker_prebuilt_ecr_image.xgboost.registry_path
}
