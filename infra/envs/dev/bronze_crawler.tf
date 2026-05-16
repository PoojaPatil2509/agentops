# ===========================================================================
# Glue Crawler — validates Bronze schema, detects drift
# ===========================================================================
# Partition projection (defined in bronze_table.tf) handles partition
# discovery automatically. This crawler exists for schema validation:
# if event shape ever changes (e.g. new field added to TraceEvent),
# the crawler picks it up and we know to update the table definition.
# Runs once daily to keep costs near zero (~$0.44 per run).
# ---------------------------------------------------------------------------

resource "aws_glue_crawler" "bronze_events" {
  name          = "${var.project_name}-${var.environment}-bronze-crawler"
  database_name = aws_glue_catalog_database.agentops.name
  role          = aws_iam_role.glue_exec.arn
  description   = "Validates Bronze events schema and detects drift"

  # Crawl the Bronze bucket events prefix
  s3_target {
    path = "s3://${aws_s3_bucket.bronze.id}/events/"
  }

  # Schedule: once daily at 02:00 UTC
  schedule = "cron(0 2 * * ? *)"

  # Schema-change policy: log changes, don't auto-modify the existing table
  schema_change_policy {
    delete_behavior = "LOG"
    update_behavior = "LOG"
  }

  # Add new partitions to our existing table rather than creating a new one
  configuration = jsonencode({
    Version = 1.0
    CrawlerOutput = {
      Partitions = { AddOrUpdateBehavior = "InheritFromTable" }
      Tables     = { AddOrUpdateBehavior = "MergeNewColumns" }
    }
    Grouping = {
      TableGroupingPolicy = "CombineCompatibleSchemas"
    }
  })

  tags = {
    Name      = "${var.project_name}-${var.environment}-bronze-crawler"
    Component = "etl"
  }
}