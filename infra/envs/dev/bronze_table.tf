# ===========================================================================
# Glue Catalog table — Bronze events schema
# ===========================================================================
# Firehose reads this schema at runtime to convert JSON → Parquet.
# Defined explicitly (not crawler-inferred) so the contract between
# producers (SDK) and consumers (Glue jobs) is reproducible.
#
# Columns mirror agentops_sdk/events.py::TraceEvent. Keep them in sync.
# ---------------------------------------------------------------------------

resource "aws_glue_catalog_table" "bronze_events" {
  name          = "bronze_events"
  database_name = aws_glue_catalog_database.agentops.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "classification"      = "parquet"
    "parquet.compression" = "GZIP"
    "projection.enabled"  = "true"
    # Partition projection: lets Athena query partitions without crawler runs.
    # Hugely useful for "show me data from the last hour" queries.
    "projection.year.type"      = "integer"
    "projection.year.range"     = "2025,2030"
    "projection.month.type"     = "integer"
    "projection.month.range"    = "1,12"
    "projection.month.digits"   = "2"
    "projection.day.type"       = "integer"
    "projection.day.range"      = "1,31"
    "projection.day.digits"     = "2"
    "projection.hour.type"      = "integer"
    "projection.hour.range"     = "0,23"
    "projection.hour.digits"    = "2"
    "storage.location.template" = "s3://${aws_s3_bucket.bronze.id}/events/year=$${year}/month=$${month}/day=$${day}/hour=$${hour}/"
  }

  partition_keys {
    name = "year"
    type = "int"
  }
  partition_keys {
    name = "month"
    type = "int"
  }
  partition_keys {
    name = "day"
    type = "int"
  }
  partition_keys {
    name = "hour"
    type = "int"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.bronze.id}/events/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      name                  = "parquet-serde"
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
      parameters = {
        "serialization.format" = "1"
      }
    }

    # Top-level fields (must match the SDK's TraceEvent model)
    # Top-level fields (must match the SDK's TraceEvent model)
    columns {
      name = "event_id"
      type = "string"
    }
    columns {
      name = "trace_id"
      type = "string"
    }
    columns {
      name = "span_id"
      type = "string"
    }
    columns {
      name = "parent_span_id"
      type = "string"
    }
    columns {
      name = "agent_name"
      type = "string"
    }
    columns {
      name = "agent_version"
      type = "string"
    }
    columns {
      name = "span_kind"
      type = "string"
    }
    columns {
      name = "span_name"
      type = "string"
    }
    columns {
      name = "start_time"
      type = "string"
    }
    columns {
      name = "end_time"
      type = "string"
    }
    columns {
      name = "duration_ms"
      type = "int"
    }
    columns {
      name = "status"
      type = "string"
    }
    columns {
      name = "error_message"
      type = "string"
    }

    # Nested objects — kept as struct so Athena can dot-access them
    columns {
      name = "llm_usage"
      type = "struct<input_tokens:int,output_tokens:int,total_tokens:int,cost_usd:double,model:string>"
    }
    columns {
      name = "input_payload"
      type = "struct<system:string,user_message:string>"
    }
    columns {
      name = "output_payload"
      type = "struct<response_preview:string>"
    }

    columns {
      name = "user_id_hashed"
      type = "string"
    }
    columns {
      name = "customer_id"
      type = "string"
    }
    columns {
      name = "sdk_version"
      type = "string"
    }
    columns {
      name = "ingested_at"
      type = "string"
    }
  }
}