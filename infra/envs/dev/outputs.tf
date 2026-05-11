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

output "lambda_exec_role_arn" {
  description = "ARN of the Lambda execution role"
  value       = aws_iam_role.lambda_exec.arn
}

output "glue_exec_role_arn" {
  description = "ARN of the Glue execution role"
  value       = aws_iam_role.glue_exec.arn
}

output "firehose_exec_role_arn" {
  description = "ARN of the Firehose execution role"
  value       = aws_iam_role.firehose_exec.arn
}

output "stepfunctions_exec_role_arn" {
  description = "ARN of the Step Functions execution role"
  value       = aws_iam_role.stepfunctions_exec.arn
}

output "alerts_topic_arn" {
  description = "SNS topic ARN for alerts"
  value       = aws_sns_topic.alerts.arn
}

output "eventbridge_bus_name" {
  description = "EventBridge custom bus name"
  value       = aws_cloudwatch_event_bus.agentops.name
}

output "anthropic_api_key_secret_arn" {
  description = "Secrets Manager ARN for the Anthropic API key"
  value       = aws_secretsmanager_secret.anthropic_api_key.arn
}

output "slack_webhook_secret_arn" {
  description = "Secrets Manager ARN for the Slack webhook"
  value       = aws_secretsmanager_secret.slack_webhook.arn
}