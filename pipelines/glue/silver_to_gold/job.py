"""
Silver → Gold Glue PySpark job.

Reads completed conversations from the Silver Iceberg table for a target
time window and aggregates them into two Gold Iceberg tables:

  gold_agent_hourly   — one row per (agent_name, customer_id, hour_bucket)
  gold_daily_summary  — one row per (agent_name, customer_id, day_bucket)

Both tables are produced by the same run. The hourly table feeds real-time
dashboards; the daily table feeds longer-term trend analysis and email
digest summaries.

Run via:
  aws glue start-job-run --job-name agentops-dev-silver-to-gold \
    --arguments file://glue_args.json

  glue_args.json:
    { "--target_year": "2026",
      "--target_month": "05",
      "--target_day": "17",
      "--target_hour": "10",
      "--silver_database": "agentops_dev",
      "--silver_table": "silver_conversations",
      "--gold_bucket": "agentops-gold-pooja",
      "--gold_database": "agentops_dev" }
"""

import sys
from awsglue.utils import getResolvedOptions
from awsglue.context import GlueContext
from pyspark.context import SparkContext
from pyspark.sql import functions as F
from pyspark.sql.window import Window

# ---------------------------------------------------------------------------
# Bootstrap Glue + Spark (Iceberg static configs come from --conf args)
# ---------------------------------------------------------------------------
args = getResolvedOptions(sys.argv, [
    "JOB_NAME",
    "target_year",
    "target_month",
    "target_day",
    "target_hour",
    "silver_database",
    "silver_table",
    "gold_bucket",
    "gold_database",
])

sc = SparkContext.getOrCreate()
glue_context = GlueContext(sc)
spark = glue_context.spark_session

# Dynamic Iceberg config — extensions and catalog come from --conf in job def
spark.conf.set(
    "spark.sql.catalog.glue_catalog.warehouse",
    f"s3://{args['gold_bucket']}/warehouse/"
)

year = int(args["target_year"])
month = int(args["target_month"])
day = int(args["target_day"])
hour = int(args["target_hour"])

silver_table = f"glue_catalog.{args['silver_database']}.{args['silver_table']}"
hourly_table = f"glue_catalog.{args['gold_database']}.gold_agent_hourly"
daily_table = f"glue_catalog.{args['gold_database']}.gold_daily_summary"

# ---------------------------------------------------------------------------
# 1. Read Silver for the target hour. We read by parsing conversation_start
#    rather than partition predicates because Silver is partitioned by
#    processed_at (when the Bronze→Silver job ran), not by conversation_start.
# ---------------------------------------------------------------------------
hour_start = f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:00:00Z"
hour_end_excl = f"{year:04d}-{month:02d}-{day:02d}T{hour + 1:02d}:00:00Z" if hour < 23 else f"{year:04d}-{month:02d}-{day + 1:02d}T00:00:00Z"

silver_df = spark.read.format("iceberg").load(silver_table)
window_df = silver_df.filter(
    (F.col("conversation_start") >= hour_start) &
    (F.col("conversation_start") <  hour_end_excl)
)

silver_count = window_df.count()
print(f"[silver_to_gold] Loaded {silver_count} conversations from Silver for hour {hour_start}")

if silver_count == 0:
    print("[silver_to_gold] Nothing to process. Exiting cleanly.")
    sys.exit(0)

# ---------------------------------------------------------------------------
# 2. Hourly aggregation — one row per (agent_name, customer_id, hour_bucket)
# ---------------------------------------------------------------------------
hourly_df = (
    window_df
    .withColumn(
        "hour_bucket",
        F.to_timestamp(F.concat(F.lit(f"{year:04d}-{month:02d}-{day:02d} "),
                                F.lit(f"{hour:02d}:00:00")))
    )
    .groupBy("agent_name", "customer_id", "hour_bucket")
    .agg(
        F.count("*").alias("conversations"),
        F.sum(F.when(F.col("conversation_status") == "error", 1).otherwise(0)).alias("error_count"),
        F.sum("total_tokens").alias("total_tokens"),
        F.sum("input_tokens").alias("input_tokens"),
        F.sum("output_tokens").alias("output_tokens"),
        F.sum("total_cost_usd").alias("total_cost_usd"),
        F.countDistinct("user_id_hashed").alias("unique_users"),
        F.expr("percentile_approx(conversation_duration_ms, 0.50)").alias("latency_p50_ms"),
        F.expr("percentile_approx(conversation_duration_ms, 0.95)").alias("latency_p95_ms"),
        F.expr("percentile_approx(conversation_duration_ms, 0.99)").alias("latency_p99_ms"),
        F.avg("llm_call_count").alias("avg_llm_calls_per_conversation"),
    )
    .withColumn(
        "error_rate_pct",
        F.round(F.col("error_count") / F.col("conversations") * 100, 2)
    )
    .withColumn("processed_at", F.current_timestamp())
)

print(f"[silver_to_gold] Built {hourly_df.count()} hourly aggregation rows")
hourly_df.show(5, truncate=False)

# ---------------------------------------------------------------------------
# 3. Create + MERGE the hourly Gold table
# ---------------------------------------------------------------------------
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {hourly_table} (
    agent_name                       STRING,
    customer_id                      STRING,
    hour_bucket                      TIMESTAMP,
    conversations                    BIGINT,
    error_count                      BIGINT,
    error_rate_pct                   DOUBLE,
    total_tokens                     BIGINT,
    input_tokens                     BIGINT,
    output_tokens                    BIGINT,
    total_cost_usd                   DOUBLE,
    unique_users                     BIGINT,
    latency_p50_ms                   BIGINT,
    latency_p95_ms                   BIGINT,
    latency_p99_ms                   BIGINT,
    avg_llm_calls_per_conversation   DOUBLE,
    processed_at                     TIMESTAMP
)
USING iceberg
PARTITIONED BY (agent_name, days(hour_bucket))
TBLPROPERTIES (
    'write.format.default' = 'parquet',
    'write.parquet.compression-codec' = 'gzip'
)
""")

hourly_df.createOrReplaceTempView("hourly_incoming")

spark.sql(f"""
MERGE INTO {hourly_table} AS t
USING hourly_incoming AS s
ON t.agent_name = s.agent_name
   AND t.customer_id = s.customer_id
   AND t.hour_bucket = s.hour_bucket
WHEN MATCHED THEN UPDATE SET
    conversations = s.conversations,
    error_count = s.error_count,
    error_rate_pct = s.error_rate_pct,
    total_tokens = s.total_tokens,
    input_tokens = s.input_tokens,
    output_tokens = s.output_tokens,
    total_cost_usd = s.total_cost_usd,
    unique_users = s.unique_users,
    latency_p50_ms = s.latency_p50_ms,
    latency_p95_ms = s.latency_p95_ms,
    latency_p99_ms = s.latency_p99_ms,
    avg_llm_calls_per_conversation = s.avg_llm_calls_per_conversation,
    processed_at = s.processed_at
WHEN NOT MATCHED THEN INSERT (
    agent_name, customer_id, hour_bucket, conversations, error_count,
    error_rate_pct, total_tokens, input_tokens, output_tokens, total_cost_usd,
    unique_users, latency_p50_ms, latency_p95_ms, latency_p99_ms,
    avg_llm_calls_per_conversation, processed_at
) VALUES (
    s.agent_name, s.customer_id, s.hour_bucket, s.conversations, s.error_count,
    s.error_rate_pct, s.total_tokens, s.input_tokens, s.output_tokens, s.total_cost_usd,
    s.unique_users, s.latency_p50_ms, s.latency_p95_ms, s.latency_p99_ms,
    s.avg_llm_calls_per_conversation, s.processed_at
)
""")

hourly_total = spark.sql(f"SELECT COUNT(*) AS n FROM {hourly_table}").collect()[0]["n"]
print(f"[silver_to_gold] gold_agent_hourly now has {hourly_total} rows")

# ---------------------------------------------------------------------------
# 4. Daily aggregation — derived from the hourly we just wrote
# ---------------------------------------------------------------------------
day_bucket_iso = f"{year:04d}-{month:02d}-{day:02d}"

daily_df = (
    spark.read.format("iceberg").load(hourly_table)
    .filter(F.date_format("hour_bucket", "yyyy-MM-dd") == day_bucket_iso)
    .groupBy("agent_name", "customer_id")
    .agg(
        F.to_date(F.lit(day_bucket_iso)).alias("day_bucket"),
        F.sum("conversations").alias("conversations"),
        F.sum("error_count").alias("error_count"),
        F.sum("total_tokens").alias("total_tokens"),
        F.sum("total_cost_usd").alias("total_cost_usd"),
        F.sum("unique_users").alias("unique_users_sum_of_hourly"),
        F.expr("percentile_approx(latency_p95_ms, 0.95)").alias("latency_p95_ms_day"),
    )
    .withColumn(
        "error_rate_pct",
        F.round(F.col("error_count") / F.col("conversations") * 100, 2)
    )
    .withColumn("processed_at", F.current_timestamp())
)

print(f"[silver_to_gold] Built {daily_df.count()} daily aggregation rows")

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {daily_table} (
    agent_name                  STRING,
    customer_id                 STRING,
    day_bucket                  DATE,
    conversations               BIGINT,
    error_count                 BIGINT,
    error_rate_pct              DOUBLE,
    total_tokens                BIGINT,
    total_cost_usd              DOUBLE,
    unique_users_sum_of_hourly  BIGINT,
    latency_p95_ms_day          BIGINT,
    processed_at                TIMESTAMP
)
USING iceberg
PARTITIONED BY (agent_name)
TBLPROPERTIES (
    'write.format.default' = 'parquet',
    'write.parquet.compression-codec' = 'gzip'
)
""")

daily_df.createOrReplaceTempView("daily_incoming")

spark.sql(f"""
MERGE INTO {daily_table} AS t
USING daily_incoming AS s
ON t.agent_name = s.agent_name
   AND t.customer_id = s.customer_id
   AND t.day_bucket = s.day_bucket
WHEN MATCHED THEN UPDATE SET
    conversations = s.conversations,
    error_count = s.error_count,
    error_rate_pct = s.error_rate_pct,
    total_tokens = s.total_tokens,
    total_cost_usd = s.total_cost_usd,
    unique_users_sum_of_hourly = s.unique_users_sum_of_hourly,
    latency_p95_ms_day = s.latency_p95_ms_day,
    processed_at = s.processed_at
WHEN NOT MATCHED THEN INSERT (
    agent_name, customer_id, day_bucket, conversations, error_count,
    error_rate_pct, total_tokens, total_cost_usd,
    unique_users_sum_of_hourly, latency_p95_ms_day, processed_at
) VALUES (
    s.agent_name, s.customer_id, s.day_bucket, s.conversations, s.error_count,
    s.error_rate_pct, s.total_tokens, s.total_cost_usd,
    s.unique_users_sum_of_hourly, s.latency_p95_ms_day, s.processed_at
)
""")

daily_total = spark.sql(f"SELECT COUNT(*) AS n FROM {daily_table}").collect()[0]["n"]
print(f"[silver_to_gold] gold_daily_summary now has {daily_total} rows")