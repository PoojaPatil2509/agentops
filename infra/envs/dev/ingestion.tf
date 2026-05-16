# ===========================================================================
# Kinesis Data Stream — buffers incoming agent events
# ===========================================================================
# On-demand mode: AWS auto-scales shards based on traffic. Costs ~$0.04/hr
# while idle plus ~$0.04 per million put requests. Cheap for portfolio scale.
# For high-volume production you'd switch to provisioned mode.

resource "aws_kinesis_stream" "events" {
  name             = "${var.project_name}-${var.environment}-events"
  retention_period = 24 # hours — minimum is 24, max 8760 (365 days)

  stream_mode_details {
    stream_mode = "ON_DEMAND"
  }

  encryption_type = "KMS"
  kms_key_id      = aws_kms_key.agentops.id

  tags = {
    Name      = "${var.project_name}-${var.environment}-events"
    Component = "ingestion"
  }
}

# ===========================================================================
# Lambda packaging — zip the handler code for deployment
# ===========================================================================

data "archive_file" "ingest_api_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../../../pipelines/lambdas/ingest_api"
  output_path = "${path.module}/.terraform/ingest_api.zip"
  excludes    = ["requirements.txt", "__pycache__", ".pytest_cache"]
}

# ===========================================================================
# Ingestion Lambda — validates events and writes to Kinesis
# ===========================================================================

resource "aws_lambda_function" "ingest_api" {
  function_name = "${var.project_name}-${var.environment}-ingest-api"
  role          = aws_iam_role.lambda_exec.arn

  filename         = data.archive_file.ingest_api_zip.output_path
  source_code_hash = data.archive_file.ingest_api_zip.output_base64sha256

  runtime     = "python3.12"
  handler     = "handler.handler"
  timeout     = 10
  memory_size = 512

  environment {
    variables = {
      KINESIS_STREAM_NAME = aws_kinesis_stream.events.name
      API_KEY_SECRET_ARN  = aws_secretsmanager_secret.ingest_api_key.arn
      LOG_LEVEL           = "INFO"
    }
  }

  # Wait for the log group to exist (we created it in Phase 1.2)
  depends_on = [aws_cloudwatch_log_group.ingest_api]

  tags = {
    Name      = "${var.project_name}-${var.environment}-ingest-api"
    Component = "ingestion"
  }
}

# ===========================================================================
# Lambda IAM extension — let it read the ingest API key secret
# ===========================================================================
# The lambda_data_access policy from Phase 1.2 covers Kinesis writes and KMS.
# We just need to add Secrets Manager read for the new secret.

data "aws_iam_policy_document" "lambda_secrets_access" {
  statement {
    sid     = "ReadIngestApiKey"
    effect  = "Allow"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.ingest_api_key.arn,
      "${aws_secretsmanager_secret.ingest_api_key.arn}-*"
    ]
  }
}

resource "aws_iam_policy" "lambda_secrets_access" {
  name        = "${var.project_name}-${var.environment}-lambda-secrets-access"
  description = "Read access to AgentOps secrets in Secrets Manager"
  policy      = data.aws_iam_policy_document.lambda_secrets_access.json
}

resource "aws_iam_role_policy_attachment" "lambda_secrets_access" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.lambda_secrets_access.arn
}

# ===========================================================================
# API Gateway HTTP API — public HTTPS endpoint for the SDK
# ===========================================================================
# HTTP APIs are cheaper, faster, and simpler than REST APIs.
# ~$1.00 per million requests vs $3.50 for REST. We don't need REST features.

resource "aws_apigatewayv2_api" "ingest" {
  name          = "${var.project_name}-${var.environment}-ingest"
  protocol_type = "HTTP"
  description   = "AgentOps ingestion HTTP API"

  cors_configuration {
    allow_origins = ["*"] # OK for dev; restrict in prod
    allow_methods = ["POST", "OPTIONS"]
    allow_headers = ["content-type", "x-api-key"]
    max_age       = 300
  }

  tags = {
    Name      = "${var.project_name}-${var.environment}-ingest-api"
    Component = "ingestion"
  }
}

# Integration: route requests to the Lambda
resource "aws_apigatewayv2_integration" "ingest_lambda" {
  api_id                 = aws_apigatewayv2_api.ingest.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.ingest_api.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
  timeout_milliseconds   = 10000
}

# Route: POST /v1/events → Lambda
resource "aws_apigatewayv2_route" "ingest_events" {
  api_id    = aws_apigatewayv2_api.ingest.id
  route_key = "POST /v1/events"
  target    = "integrations/${aws_apigatewayv2_integration.ingest_lambda.id}"
}

# Default stage with auto-deploy and access logging
resource "aws_cloudwatch_log_group" "ingest_api_gateway" {
  name              = "/aws/apigatewayv2/${var.project_name}-${var.environment}-ingest"
  retention_in_days = 14
  kms_key_id        = aws_kms_key.agentops.arn

  tags = {
    Name      = "${var.project_name}-${var.environment}-ingest-api-gw-logs"
    Component = "ingestion"
  }
}

resource "aws_apigatewayv2_stage" "ingest_default" {
  api_id      = aws_apigatewayv2_api.ingest.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.ingest_api_gateway.arn
    format = jsonencode({
      requestId        = "$context.requestId"
      ip               = "$context.identity.sourceIp"
      requestTime      = "$context.requestTime"
      httpMethod       = "$context.httpMethod"
      routeKey         = "$context.routeKey"
      status           = "$context.status"
      protocol         = "$context.protocol"
      responseLength   = "$context.responseLength"
      integrationError = "$context.integrationErrorMessage"
    })
  }

  default_route_settings {
    throttling_burst_limit = 100
    throttling_rate_limit  = 50
  }

  tags = {
    Component = "ingestion"
  }
}

# Permission: allow API Gateway to invoke the Lambda
resource "aws_lambda_permission" "apigw_invoke" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest_api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.ingest.execution_arn}/*/*"
}

# ===========================================================================
# Kinesis Firehose — drains the Data Stream to S3 Bronze as Parquet
# ===========================================================================

resource "aws_kinesis_firehose_delivery_stream" "bronze" {
  name        = "${var.project_name}-${var.environment}-to-bronze"
  destination = "extended_s3"

  # Source: the Kinesis Data Stream we already have
  kinesis_source_configuration {
    kinesis_stream_arn = aws_kinesis_stream.events.arn
    role_arn           = aws_iam_role.firehose_exec.arn
  }

  extended_s3_configuration {
    role_arn   = aws_iam_role.firehose_exec.arn
    bucket_arn = aws_s3_bucket.bronze.arn

    # Buffer settings: deliver every 60s or every 5MB, whichever first.
    # Lower = faster visibility, higher = bigger more-efficient Parquet files.
    buffering_interval = 60
    buffering_size     = 64

    # KMS encryption using our customer-managed key
    kms_key_arn = aws_kms_key.agentops.arn

    # Output prefix — Hive-style partitioning so Athena can prune
    prefix              = "events/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/"
    error_output_prefix = "errors/!{firehose:error-output-type}/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/"

    # Convert incoming JSON to Parquet using the Glue Catalog schema we defined
    data_format_conversion_configuration {
      enabled = true

      input_format_configuration {
        deserializer {
          open_x_json_ser_de {
            case_insensitive = false
          }
        }
      }

      output_format_configuration {
        serializer {
          parquet_ser_de {
            compression = "GZIP"
          }
        }
      }

      schema_configuration {
        database_name = aws_glue_catalog_database.agentops.name
        table_name    = aws_glue_catalog_table.bronze_events.name
        region        = var.aws_region
        role_arn      = aws_iam_role.firehose_exec.arn
        version_id    = "LATEST"
      }
    }

    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = aws_cloudwatch_log_group.firehose.name
      log_stream_name = "S3Delivery"
    }
  }

  tags = {
    Name      = "${var.project_name}-${var.environment}-to-bronze"
    Component = "ingestion"
  }

  depends_on = [
    aws_iam_role_policy_attachment.firehose_data_access,
    aws_glue_catalog_table.bronze_events,
  ]
}