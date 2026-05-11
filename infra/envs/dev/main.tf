# ---------------------------------------------------------------------------
# Provider configuration — tells Terraform to use AWS in your chosen region
# ---------------------------------------------------------------------------
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = var.common_tags
  }
}

# ---------------------------------------------------------------------------
# KMS key for encrypting data at rest in S3, Kinesis, etc.
# ---------------------------------------------------------------------------
resource "aws_kms_key" "agentops" {
  description             = "AgentOps encryption key for data at rest"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  tags = {
    Name = "${var.project_name}-${var.environment}-kms"
  }
}

resource "aws_kms_alias" "agentops" {
  name          = "alias/${var.project_name}-${var.environment}"
  target_key_id = aws_kms_key.agentops.key_id
}

# ---------------------------------------------------------------------------
# Bronze bucket — raw, immutable agent telemetry
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "bronze" {
  bucket = "${var.project_name}-bronze-${var.bucket_suffix}"

  tags = {
    Name  = "${var.project_name}-bronze"
    Layer = "bronze"
  }
}

resource "aws_s3_bucket_versioning" "bronze" {
  bucket = aws_s3_bucket.bronze.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "bronze" {
  bucket = aws_s3_bucket.bronze.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.agentops.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "bronze" {
  bucket                  = aws_s3_bucket.bronze.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "bronze" {
  bucket = aws_s3_bucket.bronze.id

  rule {
    id     = "transition-old-data-to-glacier"
    status = "Enabled"

    filter {}

    transition {
      days          = 30
      storage_class = "GLACIER_IR"
    }

    expiration {
      days = 365
    }
  }
}

# ---------------------------------------------------------------------------
# Silver bucket — cleaned, conformed Iceberg tables
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "silver" {
  bucket = "${var.project_name}-silver-${var.bucket_suffix}"

  tags = {
    Name  = "${var.project_name}-silver"
    Layer = "silver"
  }
}

resource "aws_s3_bucket_versioning" "silver" {
  bucket = aws_s3_bucket.silver.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "silver" {
  bucket = aws_s3_bucket.silver.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.agentops.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "silver" {
  bucket                  = aws_s3_bucket.silver.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---------------------------------------------------------------------------
# Gold bucket — aggregated, analytics-ready data
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "gold" {
  bucket = "${var.project_name}-gold-${var.bucket_suffix}"

  tags = {
    Name  = "${var.project_name}-gold"
    Layer = "gold"
  }
}

resource "aws_s3_bucket_versioning" "gold" {
  bucket = aws_s3_bucket.gold.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "gold" {
  bucket = aws_s3_bucket.gold.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.agentops.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "gold" {
  bucket                  = aws_s3_bucket.gold.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---------------------------------------------------------------------------
# Scripts and logs bucket — Glue scripts, Athena query results, access logs
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "scripts_logs" {
  bucket = "${var.project_name}-scripts-logs-${var.bucket_suffix}"

  tags = {
    Name  = "${var.project_name}-scripts-logs"
    Layer = "ops"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "scripts_logs" {
  bucket = aws_s3_bucket.scripts_logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "scripts_logs" {
  bucket                  = aws_s3_bucket.scripts_logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---------------------------------------------------------------------------
# Glue Data Catalog database — registers Iceberg tables for Athena to query
# ---------------------------------------------------------------------------
resource "aws_glue_catalog_database" "agentops" {
  name        = "${var.project_name}_${var.environment}"
  description = "AgentOps lakehouse catalog — registers Bronze/Silver/Gold tables"
}