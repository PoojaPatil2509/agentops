"""
Synthetic traffic generator.

Runs three sample agents in a loop, dispatching random requests at the
configured rate. Each agent uses the SDK to emit trace events to the
configured transport (local files in Phase 2.1, HTTP in Phase 2.2+).

Run with:
    python -m generators.run_synthetic --duration-minutes 1 --rate-per-minute 4
"""

import argparse
import random
import sys
import time
import traceback
from datetime import datetime, timedelta

from dotenv import load_dotenv
from faker import Faker
from rich.console import Console
from rich.table import Table

from agentops_sdk.tracer import Tracer
from agentops_sdk.agents import SupportBot, ResearchAgent, CodeReviewer
from generators.config import SUPPORT_QUESTIONS, RESEARCH_QUERIES, CODE_SNIPPETS

load_dotenv()
console = Console()
fake = Faker()


def build_agent_pool():
    """
    Return a list of dispatchers. Each entry is:
        (agent_label, prompt_list, dispatch_callable)
    The dispatch callable takes (user_id, prompt) and runs one conversation.
    """
    support  = SupportBot("support-bot",       Tracer("support-bot"))
    research = ResearchAgent("research-agent", Tracer("research-agent"))
    reviewer = CodeReviewer("code-reviewer",   Tracer("code-reviewer"))

    return [
        ("support-bot",    SUPPORT_QUESTIONS, lambda u, p: support.handle(user_id=u,  question=p)),
        ("research-agent", RESEARCH_QUERIES,  lambda u, p: research.handle(user_id=u, query=p)),
        ("code-reviewer",  CODE_SNIPPETS,     lambda u, p: reviewer.handle(user_id=u, snippet=p)),
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-minutes", type=float, default=5.0)
    parser.add_argument("--rate-per-minute", type=int, default=6)
    args = parser.parse_args()

    try:
        pool = build_agent_pool()
    except Exception as e:
        console.print(f"[red]Failed to build agents:[/red] {e}")
        traceback.print_exc()
        sys.exit(1)

    interval = 60.0 / args.rate_per_minute
    end_time = datetime.now() + timedelta(minutes=args.duration_minutes)
    target_events = int(args.duration_minutes * args.rate_per_minute)

    console.rule("[bold cyan]AgentOps Synthetic Traffic Generator")
    console.print(
        f"Running for [bold]{args.duration_minutes} min[/bold] "
        f"at [bold]{args.rate_per_minute}/min[/bold] "
        f"(~{target_events} events target)"
    )
    console.print(f"Agents: {', '.join(name for name, _, _ in pool)}\n")

    sent = 0
    errors = 0

    while datetime.now() < end_time:
        label, prompts, dispatch = random.choice(pool)
        prompt = random.choice(prompts)
        user_id = fake.uuid4()
        preview = prompt[:60] + ("..." if len(prompt) > 60 else "")

        try:
            dispatch(user_id, prompt)
            sent += 1
            console.print(
                f"[green]OK[/green]  {label:16s}  user={user_id[:8]}  \"{preview}\""
            )
        except Exception as e:
            errors += 1
            console.print(
                f"[red]ERR[/red] {label:16s}  user={user_id[:8]}  {type(e).__name__}: {e}"
            )

        time.sleep(interval)

    console.rule("[bold cyan]Summary")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Conversations sent", str(sent))
    table.add_row("Errors", str(errors))
    console.print(table)

    if sent == 0:
        console.print("\n[red]No events generated. Something is wrong — re-run with diagnostics:[/red]")
        console.print("  python -c \"from agentops_sdk.providers import MockProvider; print(MockProvider().invoke('x','y',50))\"")
        sys.exit(2)


if __name__ == "__main__":
    main()