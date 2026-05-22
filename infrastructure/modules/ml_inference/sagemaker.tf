# infrastructure/modules/ml_inference/sagemaker.tf

data "aws_sagemaker_prebuilt_ecr_image" "xgboost" {
  repository_name = "sagemaker-xgboost"
  image_tag       = "1.5-1"
}

# SageMaker Model — solo se crea cuando existe un modelo entrenado
resource "aws_sagemaker_model" "salary_predictor" {
  count = var.model_artifact_path != "" ? 1 : 0

  name               = "hirenovik-xgboost-${var.environment}"
  execution_role_arn = aws_iam_role.sagemaker.arn

  primary_container {
    image          = data.aws_sagemaker_prebuilt_ecr_image.xgboost.registry_path
    model_data_url = var.model_artifact_path
  }

  tags = { Name = "hirenovik-xgboost-${var.environment}", Service = "SageMaker" }
}

# Serverless endpoint config — solo se crea cuando existe modelo
resource "aws_sagemaker_endpoint_configuration" "salary_predictor" {
  count = var.model_artifact_path != "" ? 1 : 0

  name = "hirenovik-endpoint-config-${var.environment}"

  production_variants {
    variant_name = "AllTraffic"
    model_name   = aws_sagemaker_model.salary_predictor[0].name

    serverless_config {
      max_concurrency   = var.serverless_max_concurrency
      memory_size_in_mb = var.serverless_memory_size_mb
    }
  }

  tags = { Name = "hirenovik-endpoint-config-${var.environment}", Service = "SageMaker" }
}

# Endpoint — solo se crea cuando existe modelo
resource "aws_sagemaker_endpoint" "salary_predictor" {
  count = var.model_artifact_path != "" ? 1 : 0

  name                 = "hirenovik-salary-endpoint-${var.environment}"
  endpoint_config_name = aws_sagemaker_endpoint_configuration.salary_predictor[0].name

  tags = { Name = "hirenovik-salary-endpoint-${var.environment}", Service = "SageMaker" }
}