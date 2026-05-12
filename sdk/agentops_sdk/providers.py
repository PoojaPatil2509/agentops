"""
LLM provider abstraction.

Each provider knows how to make an LLM call and return a normalized result.
The Tracer/Agent code doesn't know or care which provider is in use.

Three providers:
  - MockProvider:      no API, deterministic, free. For local dev.
  - AnthropicProvider: Anthropic public API. Default for portfolio demos.
  - BedrockProvider:   AWS Bedrock. Demonstrates AWS-native LLM usage.

Select via env var:
  AGENTOPS_LLM_PROVIDER=mock|anthropic|bedrock
"""

import json
import os
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


# Approximate per-million-token pricing (USD). Update if Anthropic/AWS prices change.
PRICING = {
    # Anthropic public API — Claude Haiku 4.5
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    # Bedrock — Claude Haiku via Bedrock (same prices, different invocation path)
    "anthropic.claude-haiku-4-5-v1:0": {"input": 1.00, "output": 5.00},
    # Bedrock — Llama 3 8B Instruct (illustrative; check actual current prices)
    "meta.llama3-8b-instruct-v1:0": {"input": 0.30, "output": 0.60},
    # Bedrock — Amazon Titan Text Express
    "amazon.titan-text-express-v1": {"input": 0.20, "output": 0.60},
}


@dataclass
class LLMResult:
    """Normalized response shape across providers."""
    output_text: str
    input_tokens: int
    output_tokens: int
    model: str

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cost_usd(self) -> float:
        prices = PRICING.get(self.model, {"input": 0.0, "output": 0.0})
        return (
            self.input_tokens * prices["input"] / 1_000_000
            + self.output_tokens * prices["output"] / 1_000_000
        )


class LLMProvider(ABC):
    """Abstract LLM provider — implementations decide how the call is made."""

    @abstractmethod
    def invoke(self, system: str, user_message: str, max_tokens: int) -> LLMResult:
        ...


# ---------------------------------------------------------------------------
# 1) Mock provider — no network, no cost, deterministic-ish
# ---------------------------------------------------------------------------
class MockProvider(LLMProvider):
    """Simulates an LLM call with realistic latency, tokens, and occasional errors."""

    DEFAULT_MODEL = "mock-claude-haiku"
    ERROR_RATE = 0.05   # 5% simulated errors for anomaly detection signal

    def invoke(self, system: str, user_message: str, max_tokens: int) -> LLMResult:
        time.sleep(random.uniform(0.3, 1.5))

        if random.random() < self.ERROR_RATE:
            raise RuntimeError("Simulated transient LLM error (mock provider)")

        input_tokens = len(system.split()) + len(user_message.split()) + random.randint(5, 30)
        output_tokens = random.randint(20, max_tokens)
        return LLMResult(
            output_text=f"[MOCK] Simulated reply to: {user_message[:60]}...",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=self.DEFAULT_MODEL,
        )


# ---------------------------------------------------------------------------
# 2) Anthropic provider — uses the official anthropic Python SDK
# ---------------------------------------------------------------------------
class AnthropicProvider(LLMProvider):
    """Calls Anthropic's public API."""

    DEFAULT_MODEL = "claude-haiku-4-5-20251001"

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        # Lazy import so users on mock/bedrock don't need the package installed.
        from anthropic import Anthropic
        self.client = Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
        self.model = model or os.getenv("AGENTOPS_ANTHROPIC_MODEL", self.DEFAULT_MODEL)

    def invoke(self, system: str, user_message: str, max_tokens: int) -> LLMResult:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        output_text = response.content[0].text if response.content else ""
        return LLMResult(
            output_text=output_text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=self.model,
        )


# ---------------------------------------------------------------------------
# 3) Bedrock provider — uses boto3 + the Bedrock Runtime API
# ---------------------------------------------------------------------------
class BedrockProvider(LLMProvider):
    """
    Calls AWS Bedrock. Supports Claude, Llama, and Titan models.
    Authentication uses your AWS credentials (no API key needed).
    """

    DEFAULT_MODEL = "anthropic.claude-haiku-4-5-v1:0"

    def __init__(self, model: Optional[str] = None, region: Optional[str] = None):
        import boto3
        self.region = region or os.getenv("AWS_REGION", "eu-central-1")
        self.client = boto3.client("bedrock-runtime", region_name=self.region)
        self.model = model or os.getenv("AGENTOPS_BEDROCK_MODEL", self.DEFAULT_MODEL)

    def invoke(self, system: str, user_message: str, max_tokens: int) -> LLMResult:
        # Bedrock has different request/response shapes per model family.
        # We handle the three most common cases.

        if self.model.startswith("anthropic."):
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user_message}],
            }
            response = self.client.invoke_model(
                modelId=self.model,
                body=json.dumps(body),
                contentType="application/json",
            )
            data = json.loads(response["body"].read())
            output_text = data["content"][0]["text"] if data.get("content") else ""
            return LLMResult(
                output_text=output_text,
                input_tokens=data["usage"]["input_tokens"],
                output_tokens=data["usage"]["output_tokens"],
                model=self.model,
            )

        elif self.model.startswith("meta.llama"):
            # Llama 3 takes a single prompt string
            prompt = f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n{system}\n<|start_header_id|>user<|end_header_id|>\n{user_message}\n<|start_header_id|>assistant<|end_header_id|>\n"
            body = {
                "prompt": prompt,
                "max_gen_len": max_tokens,
                "temperature": 0.7,
            }
            response = self.client.invoke_model(
                modelId=self.model,
                body=json.dumps(body),
                contentType="application/json",
            )
            data = json.loads(response["body"].read())
            return LLMResult(
                output_text=data.get("generation", ""),
                input_tokens=data.get("prompt_token_count", 0),
                output_tokens=data.get("generation_token_count", 0),
                model=self.model,
            )

        elif self.model.startswith("amazon.titan"):
            body = {
                "inputText": f"{system}\n\nUser: {user_message}\n\nAssistant:",
                "textGenerationConfig": {
                    "maxTokenCount": max_tokens,
                    "temperature": 0.7,
                },
            }
            response = self.client.invoke_model(
                modelId=self.model,
                body=json.dumps(body),
                contentType="application/json",
            )
            data = json.loads(response["body"].read())
            result = data["results"][0]
            return LLMResult(
                output_text=result.get("outputText", ""),
                input_tokens=data.get("inputTextTokenCount", 0),
                output_tokens=result.get("tokenCount", 0),
                model=self.model,
            )

        else:
            raise ValueError(f"Bedrock model family not supported by this SDK: {self.model}")


# ---------------------------------------------------------------------------
# Factory — picks a provider based on env vars
# ---------------------------------------------------------------------------
def make_provider_from_env() -> LLMProvider:
    """Choose provider via AGENTOPS_LLM_PROVIDER env var (default: mock)."""
    name = os.getenv("AGENTOPS_LLM_PROVIDER", "mock").lower()

    if name == "mock":
        return MockProvider()
    elif name == "anthropic":
        return AnthropicProvider()
    elif name == "bedrock":
        return BedrockProvider()
    else:
        raise ValueError(
            f"Unknown AGENTOPS_LLM_PROVIDER='{name}'. "
            "Expected one of: mock, anthropic, bedrock."
        )