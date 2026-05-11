# AgentOps

Production observability and cost platform for AI agents.
Real-time telemetry ingestion, Iceberg lakehouse with medallion architecture,
anomaly detection, and natural language analytics over agent traces.

## Architecture

- **Bronze layer:** raw agent telemetry in S3 (JSON/Parquet, partitioned by hour)
- **Silver layer:** cleaned, deduplicated, PII-masked traces in Apache Iceberg
- **Gold layer:** business aggregates and ML features for dashboards and alerts
- **Real-time path:** Kinesis → Lambda → DynamoDB for live dashboard
- **Batch path:** Glue PySpark jobs orchestrated by Step Functions

## Tech Stack

AWS (S3, Kinesis, Lambda, Glue, Athena, Bedrock, DynamoDB, API Gateway, Step Functions),
Apache Iceberg, Terraform, Python, React, GitHub Actions.

## Status

Phase 0 complete. Building infrastructure foundation (Phase 1).