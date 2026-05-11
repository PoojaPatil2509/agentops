# ===========================================================================
# CloudWatch log groups with retention — controls how long we pay to store logs
# ===========================================================================

resource "aws_cloudwatch_log_group" "ingest_api" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-ingest-api"
  retention_in_days = 14
  kms_key_id        = aws_kms_key.agentops.arn

  tags = {
    Name      = "${var.project_name}-${var.environment}-ingest-api-logs"
    Component = "ingestion"
  }
}

resource "aws_cloudwatch_log_group" "stream_processor" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-stream-processor"
  retention_in_days = 14
  kms_key_id        = aws_kms_key.agentops.arn

  tags = {
    Name      = "${var.project_name}-${var.environment}-stream-processor-logs"
    Component = "processing"
  }
}

resource "aws_cloudwatch_log_group" "anomaly_detector" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-anomaly-detector"
  retention_in_days = 14
  kms_key_id        = aws_kms_key.agentops.arn

  tags = {
    Name      = "${var.project_name}-${var.environment}-anomaly-detector-logs"
    Component = "anomaly-detection"
  }
}

resource "aws_cloudwatch_log_group" "glue_jobs" {
  name              = "/aws-glue/jobs/${var.project_name}-${var.environment}"
  retention_in_days = 30
  kms_key_id        = aws_kms_key.agentops.arn

  tags = {
    Name      = "${var.project_name}-${var.environment}-glue-logs"
    Component = "etl"
  }
}

resource "aws_cloudwatch_log_group" "firehose" {
  name              = "/aws/kinesisfirehose/${var.project_name}-${var.environment}"
  retention_in_days = 14

  tags = {
    Name      = "${var.project_name}-${var.environment}-firehose-logs"
    Component = "ingestion"
  }
}

resource "aws_cloudwatch_log_group" "stepfunctions" {
  name              = "/aws/vendedlogs/states/${var.project_name}-${var.environment}"
  retention_in_days = 30

  tags = {
    Name      = "${var.project_name}-${var.environment}-stepfunctions-logs"
    Component = "orchestration"
  }
}

# ===========================================================================
# SNS topic for alerts — anomalies, pipeline failures, cost spikes
# ===========================================================================

resource "aws_sns_topic" "alerts" {
  name              = "${var.project_name}-${var.environment}-alerts"
  kms_master_key_id = aws_kms_key.agentops.id

  tags = {
    Name      = "${var.project_name}-${var.environment}-alerts"
    Component = "alerting"
  }
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ===========================================================================
# EventBridge custom bus — routes anomaly events to downstream consumers
# ===========================================================================

resource "aws_cloudwatch_event_bus" "agentops" {
  name = "${var.project_name}-${var.environment}"

  tags = {
    Name      = "${var.project_name}-${var.environment}-bus"
    Component = "eventing"
  }
}

# ===========================================================================
# Secrets Manager — holds Anthropic API key, Slack webhook, etc.
# ===========================================================================

resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name        = "${var.project_name}/${var.environment}/anthropic-api-key"
  description = "Anthropic API key for synthetic agent traffic generator"
  kms_key_id  = aws_kms_key.agentops.arn

  recovery_window_in_days = 7

  tags = {
    Name      = "${var.project_name}-${var.environment}-anthropic-key"
    Component = "secrets"
  }
}

resource "aws_secretsmanager_secret" "slack_webhook" {
  name        = "${var.project_name}/${var.environment}/slack-webhook"
  description = "Slack incoming webhook URL for alerts"
  kms_key_id  = aws_kms_key.agentops.arn

  recovery_window_in_days = 7

  tags = {
    Name      = "${var.project_name}-${var.environment}-slack-webhook"
    Component = "secrets"
  }
}