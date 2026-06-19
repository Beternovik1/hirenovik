# infrastructure/modules/data_engineering/glue_crawler.tf

resource "aws_glue_catalog_database" "main" {
  name = "hirenovik_db_${var.environment}"
}

# ---------------------------------------------------------------------------
# Crawler apunta a la capa CURATED (Parquet), NO a la capa raw (CSV).
# Los CSVs crudos tienen esquemas inconsistentes entre fechas y archivos
# sueltos en la raíz, lo que hace imposible que el Crawler genere 1 sola tabla.
# Parquet tiene esquema embebido → siempre genera exactamente 1 tabla.
# El flujo es: Raw CSV → Glue Job (PySpark) → Curated Parquet → Crawler → Catálogo
# ---------------------------------------------------------------------------

resource "aws_glue_crawler" "curated" {
  name          = "hirenovik-crawler-${var.environment}"
  database_name = aws_glue_catalog_database.main.name
  role          = aws_iam_role.glue.arn

  s3_target {
    path = "s3://${var.curated_bucket_name}/jobs/"
  }

  configuration = jsonencode({
    Version = 1.0
    CrawlerOutput = {
      Partitions = { AddOrUpdateBehavior = "InheritFromTable" }
    }
    Grouping = {
      TableGroupingPolicy = "CombineCompatibleSchemas"
    }
  })

  schema_change_policy {
    update_behavior = "LOG"
    delete_behavior = "LOG"
  }

  recrawl_policy {
    recrawl_behavior = "CRAWL_NEW_FOLDERS_ONLY"
  }

  tags = { Name = "hirenovik-crawler-${var.environment}", Service = "Glue" }
}
