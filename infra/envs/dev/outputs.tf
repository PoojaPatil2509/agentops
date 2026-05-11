output "bronze_bucket" {
  description = "Bronze layer S3 bucket name"
  value       = aws_s3_bucket.bronze.id
}

output "silver_bucket" {
  description = "Silver layer S3 bucket name"
  value       = aws_s3_bucket.silver.id
}

output "gold_bucket" {
  description = "Gold layer S3 bucket name"
  value       = aws_s3_bucket.gold.id
}

output "scripts_logs_bucket" {
  description = "Scripts and logs S3 bucket name"
  value       = aws_s3_bucket.scripts_logs.id
}

output "kms_key_arn" {
  description = "KMS key ARN for encrypting data at rest"
  value       = aws_kms_key.agentops.arn
}

output "kms_key_alias" {
  description = "KMS key alias"
  value       = aws_kms_alias.agentops.name
}

output "glue_database" {
  description = "Glue Data Catalog database name"
  value       = aws_glue_catalog_database.agentops.name
}