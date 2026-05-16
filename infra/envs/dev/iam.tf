# ===========================================================================
# IAM trust policies — define which AWS services can assume each role
# ===========================================================================

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "glue_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "firehose_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["firehose.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "stepfunctions_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

# ===========================================================================
# Lambda execution role — used by all Lambdas in this project
# ===========================================================================

resource "aws_iam_role" "lambda_exec" {
  name               = "${var.project_name}-${var.environment}-lambda-exec"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json

  tags = {
    Name = "${var.project_name}-${var.environment}-lambda-exec"
  }
}

# Permission: write logs to CloudWatch (every Lambda needs this)
resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Permission: write to Bronze bucket, read from Silver/Gold, use KMS key, write to Kinesis
data "aws_iam_policy_document" "lambda_data_access" {
  statement {
    sid     = "WriteToBronze"
    effect  = "Allow"
    actions = ["s3:PutObject", "s3:PutObjectAcl"]
    resources = [
      "${aws_s3_bucket.bronze.arn}/*"
    ]
  }

  statement {
    sid     = "ReadSilverGold"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      aws_s3_bucket.silver.arn,
      "${aws_s3_bucket.silver.arn}/*",
      aws_s3_bucket.gold.arn,
      "${aws_s3_bucket.gold.arn}/*"
    ]
  }

  statement {
    sid    = "UseKMSKey"
    effect = "Allow"
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:DescribeKey"
    ]
    resources = [aws_kms_key.agentops.arn]
  }

  statement {
    sid    = "WriteToKinesis"
    effect = "Allow"
    actions = [
      "kinesis:PutRecord",
      "kinesis:PutRecords",
      "kinesis:DescribeStream"
    ]
    resources = ["arn:aws:kinesis:${var.aws_region}:${var.aws_account_id}:stream/${var.project_name}-*"]
  }

  statement {
    sid    = "InvokeBedrock"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream"
    ]
    resources = ["arn:aws:bedrock:*::foundation-model/*"]
  }
}

resource "aws_iam_policy" "lambda_data_access" {
  name        = "${var.project_name}-${var.environment}-lambda-data-access"
  description = "Lambda access to AgentOps S3 buckets, KMS, Kinesis, and Bedrock"
  policy      = data.aws_iam_policy_document.lambda_data_access.json
}

resource "aws_iam_role_policy_attachment" "lambda_data_access" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.lambda_data_access.arn
}

# ===========================================================================
# Glue execution role — used by Glue PySpark jobs (Bronze→Silver, Silver→Gold)
# ===========================================================================

resource "aws_iam_role" "glue_exec" {
  name               = "${var.project_name}-${var.environment}-glue-exec"
  assume_role_policy = data.aws_iam_policy_document.glue_trust.json

  tags = {
    Name = "${var.project_name}-${var.environment}-glue-exec"
  }
}

resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

data "aws_iam_policy_document" "glue_data_access" {
  statement {
    sid    = "ReadBronzeWriteSilverGold"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket"
    ]
    resources = [
      aws_s3_bucket.bronze.arn,
      "${aws_s3_bucket.bronze.arn}/*",
      aws_s3_bucket.silver.arn,
      "${aws_s3_bucket.silver.arn}/*",
      aws_s3_bucket.gold.arn,
      "${aws_s3_bucket.gold.arn}/*",
      aws_s3_bucket.scripts_logs.arn,
      "${aws_s3_bucket.scripts_logs.arn}/*"
    ]
  }

  statement {
    sid    = "UseKMSKey"
    effect = "Allow"
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:DescribeKey"
    ]
    resources = [aws_kms_key.agentops.arn]
  }
}

resource "aws_iam_policy" "glue_data_access" {
  name        = "${var.project_name}-${var.environment}-glue-data-access"
  description = "Glue access to AgentOps S3 buckets and KMS"
  policy      = data.aws_iam_policy_document.glue_data_access.json
}

resource "aws_iam_role_policy_attachment" "glue_data_access" {
  role       = aws_iam_role.glue_exec.name
  policy_arn = aws_iam_policy.glue_data_access.arn
}

# ===========================================================================
# Firehose role — used by Kinesis Firehose to write from streams to S3 Bronze
# ===========================================================================

resource "aws_iam_role" "firehose_exec" {
  name               = "${var.project_name}-${var.environment}-firehose-exec"
  assume_role_policy = data.aws_iam_policy_document.firehose_trust.json

  tags = {
    Name = "${var.project_name}-${var.environment}-firehose-exec"
  }
}

data "aws_iam_policy_document" "firehose_data_access" {
  statement {
    sid    = "WriteToBronze"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:GetBucketLocation",
      "s3:GetObject",
      "s3:ListBucket",
      "s3:ListBucketMultipartUploads",
      "s3:PutObject"
    ]
    resources = [
      aws_s3_bucket.bronze.arn,
      "${aws_s3_bucket.bronze.arn}/*"
    ]
  }

  statement {
    sid    = "ReadFromKinesis"
    effect = "Allow"
    actions = [
      "kinesis:DescribeStream",
      "kinesis:GetShardIterator",
      "kinesis:GetRecords",
      "kinesis:ListShards"
    ]
    resources = ["arn:aws:kinesis:${var.aws_region}:${var.aws_account_id}:stream/${var.project_name}-*"]
  }

  statement {
    sid    = "UseKMSKey"
    effect = "Allow"
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:GenerateDataKey*",
      "kms:DescribeKey"
    ]
    resources = [aws_kms_key.agentops.arn]
  }

  statement {
    sid    = "WriteFirehoseLogs"
    effect = "Allow"
    actions = [
      "logs:PutLogEvents"
    ]
    resources = ["arn:aws:logs:${var.aws_region}:${var.aws_account_id}:log-group:/aws/kinesisfirehose/*"]
  }

  statement {
    sid    = "ReadGlueSchema"
    effect = "Allow"
    actions = [
      "glue:GetTable",
      "glue:GetTableVersion",
      "glue:GetTableVersions"
    ]
    resources = [
      "arn:aws:glue:${var.aws_region}:${var.aws_account_id}:catalog",
      "arn:aws:glue:${var.aws_region}:${var.aws_account_id}:database/${var.project_name}_${var.environment}",
      "arn:aws:glue:${var.aws_region}:${var.aws_account_id}:table/${var.project_name}_${var.environment}/*"
    ]
  }
}

resource "aws_iam_policy" "firehose_data_access" {
  name        = "${var.project_name}-${var.environment}-firehose-data-access"
  description = "Firehose access to Kinesis source and S3 Bronze destination"
  policy      = data.aws_iam_policy_document.firehose_data_access.json
}

resource "aws_iam_role_policy_attachment" "firehose_data_access" {
  role       = aws_iam_role.firehose_exec.name
  policy_arn = aws_iam_policy.firehose_data_access.arn
}

# ===========================================================================
# Step Functions role — used to orchestrate Glue and Lambda from workflows
# ===========================================================================

resource "aws_iam_role" "stepfunctions_exec" {
  name               = "${var.project_name}-${var.environment}-stepfunctions-exec"
  assume_role_policy = data.aws_iam_policy_document.stepfunctions_trust.json

  tags = {
    Name = "${var.project_name}-${var.environment}-stepfunctions-exec"
  }
}

data "aws_iam_policy_document" "stepfunctions_data_access" {
  statement {
    sid       = "InvokeLambda"
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = ["arn:aws:lambda:${var.aws_region}:${var.aws_account_id}:function:${var.project_name}-*"]
  }

  statement {
    sid    = "RunGlueJobs"
    effect = "Allow"
    actions = [
      "glue:StartJobRun",
      "glue:GetJobRun",
      "glue:GetJobRuns",
      "glue:BatchStopJobRun"
    ]
    resources = ["arn:aws:glue:${var.aws_region}:${var.aws_account_id}:job/${var.project_name}-*"]
  }

  statement {
    sid       = "PublishToSNS"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }
}

resource "aws_iam_policy" "stepfunctions_data_access" {
  name        = "${var.project_name}-${var.environment}-stepfunctions-data-access"
  description = "Step Functions access to Lambda, Glue, and SNS"
  policy      = data.aws_iam_policy_document.stepfunctions_data_access.json
}

resource "aws_iam_role_policy_attachment" "stepfunctions_data_access" {
  role       = aws_iam_role.stepfunctions_exec.name
  policy_arn = aws_iam_policy.stepfunctions_data_access.arn
}