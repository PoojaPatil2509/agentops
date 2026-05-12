"""
Transport layer — how trace events leave the SDK.

Two implementations:
- FileTransport: writes events to local JSON files (used in Phase 2.1)
- HttpTransport: POSTs events to the AgentOps ingestion API (Phase 2.2+)

The Tracer doesn't care which transport it uses. This is dependency
injection — swap transports without changing agent code.
"""

import json
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from agentops_sdk.events import TraceEvent


class Transport(ABC):
    """Abstract transport. Implementations decide where events go."""

    @abstractmethod
    def send(self, event: TraceEvent) -> None:
        ...

    @abstractmethod
    def flush(self) -> None:
        """Block until all queued events are sent."""
        ...


class FileTransport(Transport):
    """
    Writes events to local JSON-lines files, one file per minute.

    File layout: <output_dir>/year=YYYY/month=MM/day=DD/hour=HH/events-MM.jsonl
    This intentionally mirrors the S3 partitioning we'll use in Bronze later,
    so we can sanity-check the pipeline shape locally before pushing to AWS.
    """

    def __init__(self, output_dir: str = "./local_output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _path_for_now(self) -> Path:
        now = datetime.now(timezone.utc)
        partition = (
            self.output_dir
            / f"year={now.year:04d}"
            / f"month={now.month:02d}"
            / f"day={now.day:02d}"
            / f"hour={now.hour:02d}"
        )
        partition.mkdir(parents=True, exist_ok=True)
        return partition / f"events-{now.minute:02d}.jsonl"

    def send(self, event: TraceEvent) -> None:
        path = self._path_for_now()
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event.model_dump_json_compat()) + "\n")

    def flush(self) -> None:
        # FileTransport writes synchronously; nothing to flush.
        pass


class HttpTransport(Transport):
    """
    POSTs events to the AgentOps ingestion API.

    Will be wired up in Phase 2.2. Included now so the abstraction is
    complete and we can swap transports with a one-line config change.
    """

    def __init__(self, endpoint_url: str, api_key: str, timeout_seconds: float = 5.0):
        self.endpoint_url = endpoint_url
        self.api_key = api_key
        self.timeout = timeout_seconds

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=5.0),
        reraise=True,
    )
    def send(self, event: TraceEvent) -> None:
        response = httpx.post(
            self.endpoint_url,
            headers={
                "x-api-key": self.api_key,
                "content-type": "application/json",
            },
            json=event.model_dump_json_compat(),
            timeout=self.timeout,
        )
        response.raise_for_status()

    def flush(self) -> None:
        pass


def make_transport_from_env() -> Transport:
    """
    Factory that chooses transport based on environment variables.
    Falls back to FileTransport if no API endpoint configured.
    """
    endpoint = os.getenv("AGENTOPS_ENDPOINT_URL")
    api_key = os.getenv("AGENTOPS_API_KEY")

    if endpoint and api_key:
        return HttpTransport(endpoint_url=endpoint, api_key=api_key)

    output_dir = os.getenv("AGENTOPS_LOCAL_OUTPUT_DIR", "./local_output")
    return FileTransport(output_dir=output_dir)