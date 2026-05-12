"""
Event schema for AgentOps traces.

Every event represents one span of work an agent did: an LLM call,
a tool invocation, or a complete conversation. Spans are linked by
trace_id and parent_span_id, following OpenTelemetry conventions.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Any
from uuid import uuid4

from pydantic import BaseModel, Field


class SpanKind(str, Enum):
    """Type of span. Mirrors OpenTelemetry SpanKind plus AgentOps-specific kinds."""
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    CONVERSATION = "conversation"
    AGENT_RUN = "agent_run"


class SpanStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"


class LLMUsage(BaseModel):
    """Token usage and cost for an LLM call."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    model: str


class TraceEvent(BaseModel):
    """
    One span of agent activity.

    Fields chosen to match what real agent observability platforms collect:
    Langfuse, Helicone, Arize Phoenix. Hiring managers familiar with these
    tools will recognize the shape immediately.
    """
    # Identity
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    trace_id: str                          # Groups related spans into one trace
    span_id: str = Field(default_factory=lambda: str(uuid4()))
    parent_span_id: Optional[str] = None   # Tree structure within a trace

    # Classification
    agent_name: str                        # Which agent emitted this
    agent_version: str = "1.0.0"
    span_kind: SpanKind
    span_name: str                         # Human-readable: "summarize", "search_docs"

    # Timing
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: Optional[int] = None

    # Status
    status: SpanStatus = SpanStatus.OK
    error_message: Optional[str] = None

    # Data
    input_payload: Optional[dict[str, Any]] = None
    output_payload: Optional[dict[str, Any]] = None

    # LLM-specific (only set when span_kind == LLM_CALL)
    llm_usage: Optional[LLMUsage] = None

    # Tenant / user (the customer-facing dimensions for analytics)
    user_id_hashed: Optional[str] = None
    customer_id: str = "demo-customer-001"

    # Ingestion metadata
    sdk_version: str = "0.1.0"
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def model_dump_json_compat(self) -> dict:
        """Dump to a JSON-serializable dict (datetimes as ISO strings)."""
        return self.model_dump(mode="json")