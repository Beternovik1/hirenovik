locals {
  training_data_path = "s3://${var.curated_bucket_name}/training-data/"
  output_path        = "s3://${var.models_bucket_name}/xgboost/"
}

resource "aws_sfn_state_machine" "pipeline" {
  name     = "hirenovik-pipeline-${var.environment}"
  role_arn = aws_iam_role.step_functions.arn
  type     = "STANDARD"

  definition = jsonencode({
    Comment = "Hirenovik pipeline: Crawl -> Clean -> Train -> Notify"
    StartAt = "StartGlueCrawler"

    States = {
      StartGlueCrawler = {
        Type       = "Task"
        Resource   = "arn:aws:states:::glue:startCrawler.sync"
        Parameters = { Name = var.crawler_name }
        Next       = "StartGlueJob"
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            Next        = "NotifyFailure"
          }
        ]
      }

      StartGlueJob = {
        Type     = "Task"
        Resource = "arn:aws:states:::glue:startJobRun.sync"
        Parameters = {
          JobName = var.glue_job_name
          Arguments = {
            "--raw_bucket"     = var.raw_bucket_name
            "--curated_bucket" = var.curated_bucket_name
          }
        }
        Next = "StartTraining"
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            Next        = "NotifyFailure"
          }
        ]
      }

      StartTraining = {
        Type     = "Task"
        Resource = "arn:aws:states:::sagemaker:createTrainingJob.sync"
        Parameters = {
          # Dynamic name using execution name to avoid ResourceInUseException on re-runs
          "TrainingJobName.$" = "States.Format('hirenovik-xgb-{}', $$.Execution.Name)"
          RoleArn             = var.sagemaker_role_arn
          AlgorithmSpecification = {
            TrainingImage     = var.training_image
            TrainingInputMode = "File"
          }
          InputDataConfig = [
            {
              ChannelName = "train"
              ContentType = "text/csv"
              DataSource = {
                S3DataSource = {
                  S3DataType             = "S3Prefix"
                  S3Uri                  = "${local.training_data_path}train/"
                  S3DataDistributionType = "FullyReplicated"
                }
              }
            },
            {
              ChannelName = "validation"
              ContentType = "text/csv"
              DataSource = {
                S3DataSource = {
                  S3DataType             = "S3Prefix"
                  S3Uri                  = "${local.training_data_path}validation/"
                  S3DataDistributionType = "FullyReplicated"
                }
              }
            }
          ]
          OutputDataConfig   = { S3OutputPath = local.output_path }
          ResourceConfig = {
            InstanceType   = "ml.m5.large"
            InstanceCount  = 1
            VolumeSizeInGB = 20
          }
          StoppingCondition = { MaxRuntimeInSeconds = 3600 }
          HyperParameters = {
            objective        = "reg:squarederror"
            num_round        = "100"
            max_depth        = "6"
            eta              = "0.1"
            subsample        = "0.8"
            colsample_bytree = "0.8"
            eval_metric      = "rmse"
          }
        }
        Next = "NotifySuccess"
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            Next        = "NotifyFailure"
          }
        ]
      }

      # Terraform owns the endpoint — after training, update model_artifact_path and apply
      NotifySuccess = {
        Type     = "Task"
        Resource = "arn:aws:states:::sns:publish"
        Parameters = {
          TopicArn = var.sns_alert_topic_arn
          Message  = "Training completed. Model artifact saved to s3://${var.models_bucket_name}/xgboost/. Update model_artifact_path in Terraform and apply to deploy the serverless endpoint."
          Subject  = "Hirenovik Training Completed"
        }
        End = true
      }

      NotifyFailure = {
        Type     = "Task"
        Resource = "arn:aws:states:::sns:publish"
        Parameters = {
          TopicArn = var.sns_alert_topic_arn
          Message  = "Hirenovik pipeline execution failed. Check Step Functions console for details."
          Subject  = "Hirenovik Pipeline Failed"
        }
        End = true
      }
    }
  })

  tags = { Name = "hirenovik-pipeline-${var.environment}", Service = "StepFunctions" }
}
