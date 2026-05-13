from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from llm.provider import GeminiProvider
from workspace import describe_project_tree, write_files_from_agent_output

console = Console()

# Cap extracted TODO lines so one run does not fan out into dozens of API calls.
MAX_TASKS_FROM_PLAN = 12

_TASK_LINE = re.compile(
    r"^(?:[-*]|\d+\.)\s+(?:\[[ x]\]\s*)?(.+)$",
    re.IGNORECASE,
)

FILE_WRITE_INSTRUCTION = (
    "FILES ON DISK (required when you create or change code): "
    "For every file, use a separate markdown fenced code block.\n"
    "- Preferred: put the project-relative path after the language on the opening line, "
    "for example:\n"
    "```python src/main.py\n"
    "<full file contents>\n"
    "```\n"
    "- Or use a path-only fence line: ```src/main.py\n"
    "- Or start the block with a first line: # file: relative/path/to.ext\n"
    "Paths must be relative to the project root (no drive letters, no leading /, no .. ). "
    "Include enough files to complete the task."
)


def parse_plan_tasks(plan: str, max_tasks: int = MAX_TASKS_FROM_PLAN) -> list[str]:
    """Extract bullet / numbered / checkbox lines from architect Markdown."""
    seen: set[str] = set()
    tasks: list[str] = []
    for raw in plan.splitlines():
        line = raw.strip()
        if len(line) < 4 or line.startswith("#"):
            continue
        m = _TASK_LINE.match(line)
        if not m:
            continue
        text = m.group(1).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        tasks.append(text)
        if len(tasks) >= max_tasks:
            break
    return tasks


def needs_auto_fix(review_text: str) -> bool:
    upper = review_text.upper()
    return "FIX REQUIRED" in upper or "BUG" in upper


def save_to_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    console.print(f"[bold green]💾 Saved to {path}[/bold green]")


@dataclass
class Artifact:
    task: str
    code: str
    review: str


def _project_context_block(structure: str) -> str:
    return (
        "Current project directory layout (read-only snapshot; respect existing paths):\n"
        f"{structure}\n"
    )


def _engineer_for_task(
    ai: GeminiProvider,
    *,
    user_request: str,
    plan: str,
    task: str,
    dom_summary: str,
    structure: str,
) -> str:
    prompt = (
        f"{_project_context_block(structure)}\n"
        f"{FILE_WRITE_INSTRUCTION}\n\n"
        f"User request:\n{user_request}\n\n"
        f"Architect plan:\n{plan}\n\n"
        f"Project lead context (short):\n{dom_summary}\n\n"
        f"Implement ONLY this task from the plan. If the task implies multiple files, "
        f"emit one fenced block per file as described above.\n\n"
        f"Task:\n{task}"
    )
    return ai.ask("engineer", prompt)


def _review(ai: GeminiProvider, *, plan: str, task: str, code: str) -> str:
    return ai.ask(
        "reviewer",
        f"Task:\n{task}\n\nTarget Code:\n{code}\n\nOriginal Plan:\n{plan}",
    )


def _apply_fix(ai: GeminiProvider, *, review: str, code: str, structure: str) -> str:
    return ai.ask(
        "engineer",
        (
            f"{_project_context_block(structure)}\n"
            f"{FILE_WRITE_INSTRUCTION}\n\n"
            f"Fix this code based on these review comments:\n{review}\n\nCode:\n{code}"
        ),
    )


def _format_final_output(
    user_request: str,
    plan: str,
    dom_summary: str,
    artifacts: list[Artifact],
) -> str:
    parts = [
        "# Multi-agent build output\n",
        "## User request\n",
        user_request.rstrip() + "\n\n",
        "## Architect plan\n",
        plan.rstrip() + "\n\n",
        "## Dom summary\n",
        dom_summary.rstrip() + "\n\n",
    ]
    for i, a in enumerate(artifacts, start=1):
        parts.extend(
            [
                f"## Task {i}\n",
                a.task.rstrip() + "\n\n",
                "### Final code\n",
                a.code.rstrip() + "\n\n",
                "### Review\n",
                a.review.rstrip() + "\n\n",
            ]
        )
    return "".join(parts)


def _print_write_results(written: list[str], errors: list[str]) -> None:
    for w in written:
        console.print(f"[green]✓ wrote[/green] {w}")
    for e in errors:
        console.print(f"[red]✗ {e}[/red]")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Multi-agent CLI that can read a project tree and write files into it.",
    )
    p.add_argument(
        "-p",
        "--project",
        type=Path,
        default=None,
        help="Project directory to scan and write (default: MICRO_AGENT_PROJECT env or cwd).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    raw = args.project or Path(os.environ.get("MICRO_AGENT_PROJECT", "."))
    project_root = raw.expanduser().resolve()
    if not project_root.exists():
        project_root.mkdir(parents=True, exist_ok=True)
        console.print(
            f"[yellow]Created project directory:[/yellow] {project_root}"
        )

    structure = describe_project_tree(project_root)
    console.print(
        Panel(
            f"[bold]Project:[/bold] {project_root}\n\n"
            f"[dim]{structure[:4000]}{'…' if len(structure) > 4000 else ''}[/dim]",
            title="Workspace",
            border_style="cyan",
        )
    )

    ai = GeminiProvider()

    console.print(Panel("[bold magenta]Multi-Agent Coding System Active[/bold magenta]"))

    user_request = console.input("[bold cyan]What project are we building today? [/bold cyan]")

    with console.status("[bold yellow]Architect is planning..."):
        plan = ai.ask(
            "architect",
            "Plan this project. Prefer TODO items that name concrete relative file paths "
            "under the project root when possible.\n\n"
            f"User request:\n{user_request}\n\n"
            f"{_project_context_block(structure)}",
        )
    console.print(Panel(plan, title="Architect's Blueprint", border_style="yellow"))

    with console.status("[bold green]Dom is summarizing for the team..."):
        dom_summary = ai.ask(
            "dom",
            "In 2–4 short paragraphs, summarize how this project fits typical stack choices "
            "and what the team should watch for. User request:\n"
            f"{user_request}\n\nPlan:\n{plan}\n\n{structure[:6000]}",
        )
    console.print(Panel(dom_summary, title="Dom's summary", border_style="green"))

    tasks = parse_plan_tasks(plan)
    if not tasks:
        tasks = [
            "Implement the architect's plan: main entry point, project layout, "
            "and the minimum code needed to satisfy the user request."
        ]

    artifacts: list[Artifact] = []
    for idx, task in enumerate(tasks, start=1):
        with console.status(f"[bold blue]Engineer — task {idx}/{len(tasks)}..."):
            code = _engineer_for_task(
                ai,
                user_request=user_request,
                plan=plan,
                task=task,
                dom_summary=dom_summary,
                structure=structure,
            )
        console.print(
            Panel(code, title=f"Engineer — task {idx}/{len(tasks)}", border_style="blue")
        )

        written, errs = write_files_from_agent_output(project_root, code)
        _print_write_results(written, errs)

        with console.status(f"[bold red]Reviewer — task {idx}/{len(tasks)}..."):
            review = _review(ai, plan=plan, task=task, code=code)

        console.print(
            Panel(
                review,
                title=f"Review — task {idx}/{len(tasks)}",
                border_style="red",
            )
        )

        if needs_auto_fix(review):
            with console.status(f"[bold magenta]Engineer fix — task {idx}/{len(tasks)}..."):
                code = _apply_fix(ai, review=review, code=code, structure=structure)
            console.print(
                Panel(
                    code,
                    title=f"Refined code — task {idx}/{len(tasks)}",
                    border_style="green",
                )
            )
            written, errs = write_files_from_agent_output(project_root, code)
            _print_write_results(written, errs)

        artifacts.append(Artifact(task=task, code=code, review=review))

    final_output = _format_final_output(user_request, plan, dom_summary, artifacts)
    save_to_file(project_root / "final_output.txt", final_output)


if __name__ == "__main__":
    main()
