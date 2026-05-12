"""
Sample agents for synthetic traffic generation.

Each agent makes one or more LLM calls via the configured provider.
The provider is pluggable (mock / anthropic / bedrock) — agents don't care.
"""

from typing import Optional

from agentops_sdk.events import LLMUsage, SpanKind
from agentops_sdk.providers import LLMProvider, make_provider_from_env
from agentops_sdk.tracer import Tracer


class BaseAgent:
    """Common LLM-call logic shared by all sample agents."""

    def __init__(
        self,
        name: str,
        tracer: Tracer,
        provider: Optional[LLMProvider] = None,
    ):
        self.name = name
        self.tracer = tracer
        self.provider = provider or make_provider_from_env()

    def _call_llm(self, span, system: str, user_message: str, max_tokens: int = 300) -> str:
        span.set_input({"system": system, "user_message": user_message[:500]})

        result = self.provider.invoke(system=system, user_message=user_message, max_tokens=max_tokens)

        span.set_llm_usage(
            LLMUsage(
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                total_tokens=result.total_tokens,
                cost_usd=result.cost_usd,
                model=result.model,
            )
        )
        span.set_output({"response_preview": result.output_text[:500]})
        return result.output_text


class SupportBot(BaseAgent):
    """Customer support agent — handles product questions."""

    SYSTEM = (
        "You are a friendly customer support agent for a SaaS analytics product. "
        "Keep responses under 3 sentences. If unsure, suggest contacting human support."
    )

    def handle(self, user_id: str, question: str):
        with self.tracer.trace_conversation(user_id=user_id) as trace:
            with trace.span("answer_question", kind=SpanKind.LLM_CALL) as span:
                self._call_llm(span, self.SYSTEM, question, max_tokens=200)


class ResearchAgent(BaseAgent):
    """Research agent — answers technical questions with multi-step reasoning."""

    PLAN_SYSTEM = "You are a research planner. Output 2-3 bullet points outlining how to answer the question."
    ANSWER_SYSTEM = "You are a research analyst. Answer in 2-3 paragraphs using the provided plan."

    def handle(self, user_id: str, query: str):
        with self.tracer.trace_conversation(user_id=user_id) as trace:
            with trace.span("plan", kind=SpanKind.LLM_CALL) as plan_span:
                plan = self._call_llm(plan_span, self.PLAN_SYSTEM, query, max_tokens=150)
            with trace.span("answer", kind=SpanKind.LLM_CALL) as ans_span:
                self._call_llm(
                    ans_span,
                    self.ANSWER_SYSTEM,
                    f"Plan:\n{plan}\n\nQuestion: {query}",
                    max_tokens=400,
                )


class CodeReviewer(BaseAgent):
    """Code review agent — reviews a snippet and flags issues."""

    SYSTEM = (
        "You are a senior code reviewer. Given a Python snippet, list up to 3 issues "
        "or improvements as a bulleted list. Be concise."
    )

    def handle(self, user_id: str, snippet: str):
        with self.tracer.trace_conversation(user_id=user_id) as trace:
            with trace.span("review_code", kind=SpanKind.LLM_CALL) as span:
                self._call_llm(span, self.SYSTEM, snippet, max_tokens=300)