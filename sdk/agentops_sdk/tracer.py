"""
Tracer — the main SDK entry point that agents use to record spans.

Usage:
    tracer = Tracer(agent_name="support-bot")
    with tracer.trace_conversation(user_id="u123") as trace:
        with trace.span("classify_intent", kind=SpanKind.LLM_CALL) as span:
            response = call_llm(...)
            span.set_llm_usage(...)
"""

import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional, Any
from uuid import uuid4

from agentops_sdk.events import (
    TraceEvent,
    SpanKind,
    SpanStatus,
    LLMUsage,
)
from agentops_sdk.transport import Transport, make_transport_from_env


class Span:
    """One unit of work being recorded. Created via Tracer context managers."""

    def __init__(
        self,
        tracer: "Tracer",
        trace_id: str,
        parent_span_id: Optional[str],
        name: str,
        kind: SpanKind,
        user_id_hashed: Optional[str],
    ):
        self.tracer = tracer
        self.trace_id = trace_id
        self.span_id = str(uuid4())
        self.parent_span_id = parent_span_id
        self.name = name
        self.kind = kind
        self.user_id_hashed = user_id_hashed

        self.start_time = datetime.now(timezone.utc)
        self.end_time: Optional[datetime] = None
        self.status = SpanStatus.OK
        self.error_message: Optional[str] = None
        self.input_payload: Optional[dict[str, Any]] = None
        self.output_payload: Optional[dict[str, Any]] = None
        self.llm_usage: Optional[LLMUsage] = None

    def set_input(self, payload: dict[str, Any]) -> None:
        self.input_payload = payload

    def set_output(self, payload: dict[str, Any]) -> None:
        self.output_payload = payload

    def set_llm_usage(self, usage: LLMUsage) -> None:
        self.llm_usage = usage

    def set_error(self, error: Exception) -> None:
        self.status = SpanStatus.ERROR
        self.error_message = f"{type(error).__name__}: {error}"

    def _finalize_and_emit(self) -> None:
        self.end_time = datetime.now(timezone.utc)
        duration_ms = int((self.end_time - self.start_time).total_seconds() * 1000)

        event = TraceEvent(
            trace_id=self.trace_id,
            span_id=self.span_id,
            parent_span_id=self.parent_span_id,
            agent_name=self.tracer.agent_name,
            agent_version=self.tracer.agent_version,
            span_kind=self.kind,
            span_name=self.name,
            start_time=self.start_time,
            end_time=self.end_time,
            duration_ms=duration_ms,
            status=self.status,
            error_message=self.error_message,
            input_payload=self.input_payload,
            output_payload=self.output_payload,
            llm_usage=self.llm_usage,
            user_id_hashed=self.user_id_hashed,
        )
        self.tracer.transport.send(event)


class Trace:
    """Container for a logical agent run — produces child spans."""

    def __init__(self, tracer: "Tracer", user_id: Optional[str] = None):
        self.tracer = tracer
        self.trace_id = str(uuid4())
        self.user_id_hashed = (
            hashlib.sha256(user_id.encode()).hexdigest()[:16] if user_id else None
        )
        self._current_parent: Optional[str] = None

    @contextmanager
    def span(self, name: str, kind: SpanKind = SpanKind.LLM_CALL):
        span = Span(
            tracer=self.tracer,
            trace_id=self.trace_id,
            parent_span_id=self._current_parent,
            name=name,
            kind=kind,
            user_id_hashed=self.user_id_hashed,
        )
        prev_parent = self._current_parent
        self._current_parent = span.span_id
        try:
            yield span
        except Exception as e:
            span.set_error(e)
            raise
        finally:
            span._finalize_and_emit()
            self._current_parent = prev_parent


class Tracer:
    """
    Top-level SDK entry. One Tracer per agent.

    Pass a custom transport for testing; defaults to env-driven factory.
    """

    def __init__(
        self,
        agent_name: str,
        agent_version: str = "1.0.0",
        transport: Optional[Transport] = None,
    ):
        self.agent_name = agent_name
        self.agent_version = agent_version
        self.transport = transport or make_transport_from_env()

    @contextmanager
    def trace_conversation(self, user_id: Optional[str] = None):
        """Open a new trace for a conversation/agent run."""
        trace = Trace(self.tracer_self(), user_id=user_id)
        with trace.span("conversation", kind=SpanKind.CONVERSATION) as root:
            yield trace

    def tracer_self(self) -> "Tracer":
        return self

    def flush(self) -> None:
        self.transport.flush()