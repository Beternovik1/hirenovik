# infrastructure/environments/dev/main.tf

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "Hirenovik"
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

module "storage" {
  source      = "../../modules/storage"
  environment = var.environment
}

module "data_engineering" {
  source              = "../../modules/data_engineering"
  environment         = var.environment
  raw_bucket_name     = module.storage.raw_bucket_name
  raw_bucket_arn      = module.storage.raw_bucket_arn
  curated_bucket_name = module.storage.curated_bucket_name
  curated_bucket_arn  = module.storage.curated_bucket_arn
  region              = var.aws_region
}

module "ml_inference" {
  source              = "../../modules/ml_inference"
  environment         = var.environment
  curated_bucket_arn  = module.storage.curated_bucket_arn
  models_bucket_name  = module.storage.models_bucket_name
  models_bucket_arn   = module.storage.models_bucket_arn
  region              = var.aws_region
  input_bucket_name   = module.storage.input_bucket_name
  input_bucket_arn    = module.storage.input_bucket_arn
  raw_bucket_name     = module.storage.raw_bucket_name
  model_artifact_path = var.model_artifact_path
}

module "orchestration" {
  source              = "../../modules/orchestration"
  environment         = var.environment
  region              = var.aws_region
  crawler_name        = module.data_engineering.crawler_name
  glue_job_name       = module.data_engineering.job_name
  sagemaker_role_arn  = module.ml_inference.sagemaker_role_arn
  sns_alert_topic_arn = module.ml_inference.sns_topic_arn
  training_image      = module.ml_inference.training_image_uri
  raw_bucket_name     = module.storage.raw_bucket_name
  curated_bucket_name = module.storage.curated_bucket_name
  models_bucket_name  = module.storage.models_bucket_name
}

module "observability" {
  source               = "../../modules/observability"
  environment          = var.environment
  region               = var.aws_region
  curated_bucket_name  = module.storage.curated_bucket_name
  endpoint_name        = module.ml_inference.endpoint_name
  lambda_function_name = module.ml_inference.lambda_function_name
  sns_alert_topic_arn  = module.ml_inference.sns_topic_arn
  glue_job_name        = module.data_engineering.job_name
  state_machine_arn    = module.orchestration.state_machine_arn
}
