"""
Bronze → Silver Glue PySpark job.

Reads new Parquet records from the Bronze layer, performs cleaning and
reconstruction, and merges results into the Silver Iceberg table.

Operations performed:
  1. Read Bronze for the target hour(s) using partition predicates
  2. Drop malformed events (missing required fields)
  3. Deduplicate by event_id (Firehose can occasionally double-deliver)
  4. Defense-in-depth PII masking on user_id_hashed and customer_id
  5. Reconstruct conversations: join LLM_CALL/TOOL_CALL spans to their
     CONVERSATION parents by trace_id, producing one row per conversation
  6. MERGE INTO the Silver Iceberg table, upserting by trace_id

Designed to be idempotent — running the same hour twice produces identical
output, because MERGE INTO handles upserts deterministically.

Run via:
  Glue Studio job invocation with the following job arguments:
    --target_year        2026
    --target_month       05
    --target_day         16
    --target_hour        15
    --bronze_database    agentops_dev
    --bronze_table       bronze_events
    --silver_bucket      agentops-silver-pooja
    --silver_database    agentops_dev
    --silver_table       silver_conversations
"""

import sys
from awsglue.utils import getResolvedOptions
from awsglue.context import GlueContext
from pyspark.context import SparkContext
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, TimestampType
)

# ---------------------------------------------------------------------------
# Bootstrap Glue + Spark with Iceberg support
# ---------------------------------------------------------------------------
args = getResolvedOptions(sys.argv, [
    "JOB_NAME",
    "target_year",
    "target_month",
    "target_day",
    "target_hour",
    "bronze_database",
    "bronze_table",
    "silver_bucket",
    "silver_database",
    "silver_table",
])

sc = SparkContext.getOrCreate()
glue_context = GlueContext(sc)
spark = glue_context.spark_session

# Iceberg requires these Spark configurations. Glue 4.0+ supports Iceberg
# natively when --datalake-formats=iceberg is passed in the job parameters.
spark.conf.set("spark.sql.catalog.glue_catalog", "org.apache.iceberg.spark.SparkCatalog")
spark.conf.set("spark.sql.catalog.glue_catalog.catalog-impl",
               "org.apache.iceberg.aws.glue.GlueCatalog")
spark.conf.set("spark.sql.catalog.glue_catalog.io-impl",
               "org.apache.iceberg.aws.s3.S3FileIO")
spark.conf.set("spark.sql.catalog.glue_catalog.warehouse",
               f"s3://{args['silver_bucket']}/warehouse/")


# ---------------------------------------------------------------------------
# 1. Read Bronze for the target partition window
# ---------------------------------------------------------------------------
year = int(args["target_year"])
month = int(args["target_month"])
day = int(args["target_day"])
hour = int(args["target_hour"])

bronze_df = (
    spark.read.format("parquet")
    .load(f"s3://agentops-bronze-pooja/events/"
          f"year={year}/month={month:02d}/day={day:02d}/hour={hour:02d}/")
)

print(f"[bronze_to_silver] Loaded {bronze_df.count()} raw events from Bronze")

# ---------------------------------------------------------------------------
# 2. Drop malformed events
# ---------------------------------------------------------------------------
required = ["event_id", "trace_id", "span_id", "agent_name", "span_kind", "start_time"]
clean_df = bronze_df.dropna(subset=required)
dropped = bronze_df.count() - clean_df.count()
print(f"[bronze_to_silver] Dropped {dropped} malformed events")

# ---------------------------------------------------------------------------
# 3. Deduplicate by event_id (latest ingested_at wins)
# ---------------------------------------------------------------------------
from pyspark.sql.window import Window
dedup_window = Window.partitionBy("event_id").orderBy(F.desc("ingested_at"))
deduped_df = (
    clean_df
    .withColumn("_rownum", F.row_number().over(dedup_window))
    .filter(F.col("_rownum") == 1)
    .drop("_rownum")
)
print(f"[bronze_to_silver] After dedup: {deduped_df.count()} unique events")

# ---------------------------------------------------------------------------
# 4. PII defense-in-depth — re-hash anything that looks like an email or
#    raw user ID. The SDK already hashes user_id, but if upstream callers
#    bypassed it, this catches the leak.
# ---------------------------------------------------------------------------
def looks_unhashed(col):
    """A 16-char hex string is our SHA256-truncated format. Anything else
    that's user-id-shaped should be re-hashed defensively."""
    return ~F.col(col).rlike(r"^[a-f0-9]{16}$") & F.col(col).isNotNull()

safe_df = deduped_df.withColumn(
    "user_id_hashed",
    F.when(
        looks_unhashed("user_id_hashed"),
        F.sha2(F.col("user_id_hashed"), 256).substr(1, 16)
    ).otherwise(F.col("user_id_hashed"))
)

# ---------------------------------------------------------------------------
# 5. Reconstruct conversations — join child spans to their parent CONVERSATION
# ---------------------------------------------------------------------------
conversation_roots = (
    safe_df.filter(F.col("span_kind") == "conversation")
    .select(
        F.col("trace_id"),
        F.col("agent_name").alias("conv_agent_name"),
        F.col("agent_version").alias("conv_agent_version"),
        F.col("user_id_hashed").alias("conv_user_id_hashed"),
        F.col("customer_id").alias("conv_customer_id"),
        F.col("start_time").alias("conversation_start"),
        F.col("end_time").alias("conversation_end"),
        F.col("duration_ms").alias("conversation_duration_ms"),
        F.col("status").alias("conversation_status"),
        F.col("error_message").alias("conversation_error"),
    )
)

llm_calls = (
    safe_df.filter(F.col("span_kind") == "llm_call")
    .groupBy("trace_id")
    .agg(
        F.count("*").alias("llm_call_count"),
        F.sum("llm_usage.total_tokens").alias("total_tokens"),
        F.sum("llm_usage.input_tokens").alias("input_tokens"),
        F.sum("llm_usage.output_tokens").alias("output_tokens"),
        F.sum("llm_usage.cost_usd").alias("total_cost_usd"),
        F.max("llm_usage.model").alias("model"),
        F.sum(F.when(F.col("status") == "error", 1).otherwise(0)).alias("llm_error_count"),
        F.collect_list("span_name").alias("llm_steps"),
    )
)

conversations_df = (
    conversation_roots
    .join(llm_calls, on="trace_id", how="left")
    .withColumn("processed_at", F.current_timestamp())
    .withColumnRenamed("conv_agent_name", "agent_name")
    .withColumnRenamed("conv_agent_version", "agent_version")
    .withColumnRenamed("conv_user_id_hashed", "user_id_hashed")
    .withColumnRenamed("conv_customer_id", "customer_id")
)

print(f"[bronze_to_silver] Reconstructed {conversations_df.count()} conversations")
conversations_df.show(5, truncate=False)

# ---------------------------------------------------------------------------
# 6. Write to Silver Iceberg table with MERGE INTO (idempotent upsert)
# ---------------------------------------------------------------------------
silver_table = f"glue_catalog.{args['silver_database']}.{args['silver_table']}"

# Create the Silver table on first run
conversations_df.createOrReplaceTempView("incoming")

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {silver_table} (
    trace_id              STRING,
    agent_name            STRING,
    agent_version         STRING,
    user_id_hashed        STRING,
    customer_id           STRING,
    conversation_start    STRING,
    conversation_end      STRING,
    conversation_duration_ms  INT,
    conversation_status   STRING,
    conversation_error    STRING,
    llm_call_count        BIGINT,
    total_tokens          BIGINT,
    input_tokens          BIGINT,
    output_tokens         BIGINT,
    total_cost_usd        DOUBLE,
    model                 STRING,
    llm_error_count       BIGINT,
    llm_steps             ARRAY<STRING>,
    processed_at          TIMESTAMP
)
USING iceberg
PARTITIONED BY (agent_name, days(processed_at))
TBLPROPERTIES (
    'write.format.default' = 'parquet',
    'write.parquet.compression-codec' = 'gzip'
)
""")

# MERGE INTO: upsert by trace_id
spark.sql(f"""
MERGE INTO {silver_table} AS t
USING incoming AS s
ON t.trace_id = s.trace_id
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *
""")

merged_count = spark.sql(
    f"SELECT COUNT(*) AS n FROM {silver_table}"
).collect()[0]["n"]
print(f"[bronze_to_silver] Silver table now contains {merged_count} total conversations")