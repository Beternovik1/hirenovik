# infrastructure/modules/data_engineering/glue_crawler.tf

resource "aws_glue_catalog_database" "main" {
  name = "hirenovik_db_${var.environment}"
}

resource "aws_glue_crawler" "supabase_exports" {
  name          = "hirenovik-crawler-${var.environment}"
  database_name = aws_glue_catalog_database.main.name
  role          = aws_iam_role.glue.arn

  s3_target {
    path = "s3://${var.raw_bucket_name}/supabase_exports/"
  }

  configuration = jsonencode({
    Version = 1.0
    CrawlerOutput = {
      Partitions = { AddOrUpdateBehavior = "InheritFromTable" }
    }
  })

  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "DEPRECATE_IN_DATABASE"
  }

  lineage_configuration {
    crawler_lineage_settings = "ENABLE"
  }

  recrawl_policy {
    recrawl_behavior = "CRAWL_NEW_FOLDERS_ONLY"
  }

  tags = { Name = "hirenovik-crawler-${var.environment}", Service = "Glue" }
}
