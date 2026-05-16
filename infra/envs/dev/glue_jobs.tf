# ===========================================================================
# Upload the Bronze→Silver script to S3 (Glue reads scripts from S3, not git)
# ===========================================================================

resource "aws_s3_object" "bronze_to_silver_script" {
  bucket = aws_s3_bucket.scripts_logs.id
  key    = "glue-scripts/bronze_to_silver/job.py"
  source = "${path.module}/../../../pipelines/glue/bronze_to_silver/job.py"
  etag   = filemd5("${path.module}/../../../pipelines/glue/bronze_to_silver/job.py")

  tags = {
    Name      = "${var.project_name}-${var.environment}-bronze-to-silver-script"
    Component = "etl"
  }
}

# ===========================================================================
# Glue PySpark job — Bronze → Silver
# ===========================================================================

resource "aws_glue_job" "bronze_to_silver" {
  name              = "${var.project_name}-${var.environment}-bronze-to-silver"
  description       = "Reads Bronze Parquet, dedupes, masks PII, reconstructs conversations, writes Silver Iceberg"
  role_arn          = aws_iam_role.glue_exec.arn
  glue_version      = "4.0"
  worker_type       = "G.1X"
  number_of_workers = 2
  timeout           = 10 # minutes — small jobs only

  command {
    script_location = "s3://${aws_s3_bucket.scripts_logs.id}/${aws_s3_object.bronze_to_silver_script.key}"
    python_version  = "3"
  }

  default_arguments = {
    "--job-language"                     = "python"
    "--datalake-formats"                 = "iceberg"
    "--enable-continuous-cloudwatch-log" = "true"
    "--enable-metrics"                   = "true"
    "--enable-spark-ui"                  = "false" # saves DPU minutes
    "--spark-event-logs-path"            = "s3://${aws_s3_bucket.scripts_logs.id}/glue-spark-logs/"
    "--TempDir"                          = "s3://${aws_s3_bucket.scripts_logs.id}/glue-temp/"

    # Iceberg static configs (must be passed as Spark conf at startup, not runtime)
    "--conf" = "spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions --conf spark.sql.catalog.glue_catalog=org.apache.iceberg.spark.SparkCatalog --conf spark.sql.catalog.glue_catalog.warehouse=s3://${aws_s3_bucket.silver.id}/warehouse/ --conf spark.sql.catalog.glue_catalog.catalog-impl=org.apache.iceberg.aws.glue.GlueCatalog --conf spark.sql.catalog.glue_catalog.io-impl=org.apache.iceberg.aws.s3.S3FileIO"

    # Defaults — Step Functions will override these per run
    "--bronze_database" = aws_glue_catalog_database.agentops.name
    "--bronze_table"    = aws_glue_catalog_table.bronze_events.name
    "--silver_bucket"   = aws_s3_bucket.silver.id
    "--silver_database" = aws_glue_catalog_database.agentops.name
    "--silver_table"    = "silver_conversations"
  }

  execution_property {
    max_concurrent_runs = 1
  }

  tags = {
    Name      = "${var.project_name}-${var.environment}-bronze-to-silver"
    Component = "etl"
  }
}

# ===========================================================================
# Silver → Gold Glue job
# ===========================================================================

resource "aws_s3_object" "silver_to_gold_script" {
  bucket = aws_s3_bucket.scripts_logs.id
  key    = "glue-scripts/silver_to_gold/job.py"
  source = "${path.module}/../../../pipelines/glue/silver_to_gold/job.py"
  etag   = filemd5("${path.module}/../../../pipelines/glue/silver_to_gold/job.py")

  tags = {
    Name      = "${var.project_name}-${var.environment}-silver-to-gold-script"
    Component = "etl"
  }
}

resource "aws_glue_job" "silver_to_gold" {
  name              = "${var.project_name}-${var.environment}-silver-to-gold"
  description       = "Aggregates Silver conversations into hourly and daily Gold tables (Iceberg)"
  role_arn          = aws_iam_role.glue_exec.arn
  glue_version      = "4.0"
  worker_type       = "G.1X"
  number_of_workers = 2
  timeout           = 10

  command {
    script_location = "s3://${aws_s3_bucket.scripts_logs.id}/${aws_s3_object.silver_to_gold_script.key}"
    python_version  = "3"
  }

  default_arguments = {
    "--job-language"                     = "python"
    "--datalake-formats"                 = "iceberg"
    "--enable-continuous-cloudwatch-log" = "true"
    "--enable-metrics"                   = "true"
    "--enable-spark-ui"                  = "false"
    "--spark-event-logs-path"            = "s3://${aws_s3_bucket.scripts_logs.id}/glue-spark-logs/"
    "--TempDir"                          = "s3://${aws_s3_bucket.scripts_logs.id}/glue-temp/"

    # Iceberg static configs — same shape as bronze_to_silver
    "--conf" = "spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions --conf spark.sql.catalog.glue_catalog=org.apache.iceberg.spark.SparkCatalog --conf spark.sql.catalog.glue_catalog.warehouse=s3://${aws_s3_bucket.gold.id}/warehouse/ --conf spark.sql.catalog.glue_catalog.catalog-impl=org.apache.iceberg.aws.glue.GlueCatalog --conf spark.sql.catalog.glue_catalog.io-impl=org.apache.iceberg.aws.s3.S3FileIO"

    "--silver_database" = aws_glue_catalog_database.agentops.name
    "--silver_table"    = "silver_conversations"
    "--gold_bucket"     = aws_s3_bucket.gold.id
    "--gold_database"   = aws_glue_catalog_database.agentops.name
  }

  execution_property {
    max_concurrent_runs = 1
  }

  tags = {
    Name      = "${var.project_name}-${var.environment}-silver-to-gold"
    Component = "etl"
  }
}