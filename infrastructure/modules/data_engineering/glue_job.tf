# infrastructure/modules/data_engineering/glue_job.tf

resource "aws_s3_object" "glue_script" {
  bucket = var.raw_bucket_name
  key    = "glue_scripts/clean_and_curate.py"
  source = "${path.module}/../../../src/glue_jobs/clean_and_curate.py"
  etag   = filemd5("${path.module}/../../../src/glue_jobs/clean_and_curate.py")
}

resource "aws_glue_job" "clean_and_curate" {
  name              = "hirenovik-cleaning-job-${var.environment}"
  role_arn          = aws_iam_role.glue.arn
  glue_version      = "4.0"
  worker_type       = "G.1X"
  number_of_workers = 2
  timeout           = 60
  max_retries       = 0

  command {
    script_location = "s3://${var.raw_bucket_name}/glue_scripts/clean_and_curate.py"
    python_version  = "3"
  }

  default_arguments = {
    "--raw_bucket"                       = var.raw_bucket_name
    "--curated_bucket"                   = var.curated_bucket_name
    "--job-language"                     = "python"
    "--job-bookmark-option"              = "job-bookmark-disable"
    "--enable-continuous-cloudwatch-log" = "true"
    "--enable-metrics"                   = "true"
  }

  tags = { Name = "hirenovik-cleaning-job-${var.environment}", Service = "Glue" }

  depends_on = [aws_s3_object.glue_script]
}
