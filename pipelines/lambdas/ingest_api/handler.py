"""
AgentOps ingestion Lambda.

Receives JSON trace events via API Gateway HTTP API, validates the API key,
checks the event shape, and writes to Kinesis Data Stream.

This is the only externally-reachable component of the platform. Keep it
small and fast — every millisecond costs money at scale.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import time
import uuid

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Read config once at cold start
KINESIS_STREAM_NAME = os.environ["KINESIS_STREAM_NAME"]
API_KEY_SECRET_ARN = os.environ["API_KEY_SECRET_ARN"]

# Initialize clients outside the handler so they're reused across invocations
kinesis = boto3.client("kinesis")
secrets = boto3.client("secretsmanager")

# Cache the API key in module scope. Lambda reuses the execution environment
# between invocations, so this dramatically reduces Secrets Manager calls.
_cached_api_key = None


def _get_api_key() -> str:
    """Fetch the API key from Secrets Manager, cached after first call."""
    global _cached_api_key
    if _cached_api_key is None:
        response = secrets.get_secret_value(SecretId=API_KEY_SECRET_ARN)
        _cached_api_key = response["SecretString"]
    return _cached_api_key


def _response(status_code: int, body: dict) -> dict:
    """Standard API Gateway HTTP API response shape."""
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }


def _validate_event_shape(event_data: dict) -> tuple[bool, str]:
    """
    Lightweight schema validation. We don't enforce full Pydantic here
    (would add cold-start latency) — just the must-have fields.
    Full validation happens in the Bronze→Silver Glue job in Phase 3.
    """
    required = ["trace_id", "span_id", "agent_name", "span_kind", "start_time"]
    missing = [k for k in required if k not in event_data]
    if missing:
        return False, f"missing required fields: {missing}"
    return True, ""


def handler(event, context):
    """
    Lambda entry point. API Gateway HTTP API invokes us with this event shape:
      { "headers": {"x-api-key": "..."}, "body": "<json string>", ... }
    """
    request_id = context.aws_request_id if context else str(uuid.uuid4())

    # --- Auth: constant-time API key comparison
    headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
    provided_key = headers.get("x-api-key", "")
    expected_key = _get_api_key()

    if not hmac.compare_digest(provided_key, expected_key):
        logger.warning(f"[{request_id}] auth_failed")
        return _response(401, {"error": "unauthorized"})

    # --- Parse body
    raw_body = event.get("body", "")
    if event.get("isBase64Encoded"):
        raw_body = base64.b64decode(raw_body).decode("utf-8")

    try:
        event_data = json.loads(raw_body)
    except json.JSONDecodeError as e:
        logger.warning(f"[{request_id}] invalid_json: {e}")
        return _response(400, {"error": "invalid_json", "detail": str(e)})

    # --- Validate event shape
    ok, reason = _validate_event_shape(event_data)
    if not ok:
        logger.warning(f"[{request_id}] invalid_event: {reason}")
        return _response(400, {"error": "invalid_event", "detail": reason})

    # --- Write to Kinesis
    # Partition key = trace_id ensures all spans for one conversation land
    # on the same shard, preserving ordering for downstream consumers.
    try:
        result = kinesis.put_record(
            StreamName=KINESIS_STREAM_NAME,
            Data=raw_body.encode("utf-8"),
            PartitionKey=event_data["trace_id"],
        )
        logger.info(
            f"[{request_id}] event_accepted "
            f"trace_id={event_data['trace_id']} "
            f"agent={event_data.get('agent_name')} "
            f"shard={result.get('ShardId')}"
        )
    except Exception as e:
        logger.exception(f"[{request_id}] kinesis_put_failed")
        return _response(503, {"error": "ingestion_failed", "detail": str(e)})

    return _response(202, {
        "status": "accepted",
        "event_id": event_data.get("event_id"),
        "request_id": request_id,
    })