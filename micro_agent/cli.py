"""Console script entry: run from any directory; use -p for the target project folder."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel


def main() -> None:
    from llm.errors import LLMRequestError
    from manager import main as run_agent

    console = Console()
    try:
        run_agent()
    except LLMRequestError as e:
        console.print(
            Panel(
                str(e),
                title="LLM request problem",
                border_style="red",
            )
        )
        raise SystemExit(1) from e
