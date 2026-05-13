"""Console script entry: run from any directory; use -p for the target project folder."""

from __future__ import annotations


def main() -> None:
    # Top-level modules (manager, workspace, dev_runner) are installed via py-modules.
    from manager import main as run_agent

    run_agent()
