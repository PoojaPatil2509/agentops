# AgentOps SDK

Python SDK for instrumenting AI agents. Wraps LLM calls with OpenTelemetry-style trace events and ships them to the AgentOps ingestion API (or local files during development).

## Features

- **Pluggable LLM providers** — switch between mock, Anthropic API, and AWS Bedrock via one env var.
- **Pluggable transports** — write events to local JSON files (dev) or POST to the AgentOps HTTP API (prod).
- **Context-manager API** — automatic timing, error capture, and parent/child span linkage.
- **PII hashing** — user IDs are SHA-256 hashed at the SDK boundary; raw IDs never leave the agent process.
- **Typed event schema** — Pydantic models with full validation; no malformed events reach the pipeline.

## Quickstart

```bash
# Create and activate a venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows
source .venv/bin/activate      # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment
copy .env.example .env         # Windows
cp .env.example .env           # macOS/Linux
# Edit .env — defaults to mock provider (no API key needed)

# Run the synthetic traffic generator
python -m generators.run_synthetic --duration-minutes 1 --rate-per-minute 4
```

Events land in `./local_output/year=YYYY/month=MM/day=DD/hour=HH/events-MM.jsonl`.

## LLM Providers

| Provider  | Setup                                      | Cost          | Use case                          |
|-----------|--------------------------------------------|---------------|-----------------------------------|
| `mock`    | None — works out of the box                | Free          | Development, CI, fast iteration   |
| `anthropic` | Set `ANTHROPIC_API_KEY` in `.env`        | ~$0.20–0.50/hr | Realistic portfolio demo data    |
| `bedrock` | AWS credentials + model use-case prompt    | ~$0.10–0.50/hr | AWS-native demo, IAM-based auth   |

Switch by setting `AGENTOPS_LLM_PROVIDER=mock|anthropic|bedrock` in `.env`.

For Bedrock, select model via `AGENTOPS_BEDROCK_MODEL`:
- `anthropic.claude-haiku-4-5-v1:0` (default)
- `meta.llama3-8b-instruct-v1:0`
- `amazon.titan-text-express-v1`

## Architecture
agentops_sdk/
├── events.py      # Pydantic event models (TraceEvent, LLMUsage)
├── tracer.py      # Tracer + Trace + Span context-manager API
├── providers.py   # MockProvider, AnthropicProvider, BedrockProvider
├── transport.py   # FileTransport, HttpTransport (DI-swappable)
└── agents.py      # Sample agents (SupportBot, ResearchAgent, CodeReviewer)
generators/
├── config.py          # Sample prompts for synthetic traffic
└── run_synthetic.py   # Runs agents in a loop at a configurable rate

### Event schema

Each `TraceEvent` records one span of work. Key fields:

| Field | Purpose |
|-------|---------|
| `trace_id` | Groups all spans from one conversation |
| `span_id` / `parent_span_id` | Tree structure within a trace |
| `agent_name` / `agent_version` | Which agent emitted the span |
| `span_kind` | `conversation`, `llm_call`, `tool_call`, `agent_run` |
| `duration_ms` | End-to-end span latency |
| `status` / `error_message` | OK / error / timeout + reason |
| `llm_usage` | Tokens in/out, cost, model |
| `user_id_hashed` | SHA-256 of caller's user ID (first 16 chars) |
| `customer_id` | Tenant identifier |

## Verifying a Run

After running the generator:

```powershell
# Count events by agent
Get-ChildItem -Recurse local_output -Filter "*.jsonl" |
  Get-Content | ConvertFrom-Json |
  Group-Object agent_name | Select-Object Name, Count

# Inspect one event
$f = Get-ChildItem -Recurse local_output -Filter "*.jsonl" | Select-Object -First 1
Get-Content $f.FullName | Select-Object -First 1
```

## Roadmap

- **Phase 2.2** — `HttpTransport` activated against deployed API Gateway endpoint
- **Phase 3** — Bronze→Silver Glue job consumes these events
- **Phase 4** — SDK published as a `pip install agentops-sdk` package