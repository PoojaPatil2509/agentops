# ===========================================================================
# Athena workgroup — isolates queries, enforces output location and cost cap
# ===========================================================================

resource "aws_athena_workgroup" "agentops" {
  name        = "${var.project_name}-${var.environment}"
  description = "AgentOps Athena workgroup with query result encryption"
  state       = "ENABLED"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    # Cap query data scan at 1 GB per query — prevents accidental
    # scans of the full Bronze bucket eating your budget
    bytes_scanned_cutoff_per_query = 1073741824 # 1 GB

    result_configuration {
      output_location = "s3://${aws_s3_bucket.scripts_logs.id}/athena-results/"

      encryption_configuration {
        encryption_option = "SSE_KMS"
        kms_key_arn       = aws_kms_key.agentops.arn
      }
    }
  }

  tags = {
    Name      = "${var.project_name}-${var.environment}-athena"
    Component = "analytics"
  }
}