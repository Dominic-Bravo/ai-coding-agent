from __future__ import annotations

import argparse
import os
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from dev_runner import RunResult, run_dev_command, validate_dev_command
from llm.provider import GeminiProvider
from workspace import (
    collect_project_markdown_docs,
    describe_project_tree,
    extract_todo_lines_from_markdown,
    write_files_from_agent_output,
)

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


def _markdown_digest_block(md_bundle: str, *, limit: int = 10_000) -> str:
    if not md_bundle.strip():
        return ""
    if len(md_bundle) <= limit:
        body = md_bundle
    else:
        body = md_bundle[:limit] + "\n… (markdown digest truncated)\n"
    return f"Project markdown (specs / TODOs / notes):\n{body}\n"


def _markdown_docs_for_architect(md_bundle: str) -> str:
    return (
        "PROJECT MARKDOWN (read this section FIRST; it may contain specs, TODO lists, or notes):\n"
        f"{md_bundle}\n"
    )


def _engineer_for_task(
    ai: GeminiProvider,
    *,
    user_request: str,
    plan: str,
    task: str,
    dom_summary: str,
    structure: str,
    markdown_digest: str,
) -> str:
    prompt = (
        f"{_project_context_block(structure)}\n"
        f"{_markdown_digest_block(markdown_digest)}\n"
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


def _apply_fix(ai: GeminiProvider, *, review: str, code: str, structure: str, markdown_digest: str) -> str:
    return ai.ask(
        "engineer",
        (
            f"{_project_context_block(structure)}\n"
            f"{_markdown_digest_block(markdown_digest)}\n"
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


def _resolve_project_root(project_arg: Path | None) -> Path:
    raw = project_arg or Path(os.environ.get("MICRO_AGENT_PROJECT", "."))
    project_root = raw.expanduser().resolve()
    if not project_root.exists():
        project_root.mkdir(parents=True, exist_ok=True)
        console.print(
            f"[yellow]Created project directory:[/yellow] {project_root}"
        )
    return project_root


def _print_run_result(result: RunResult) -> None:
    cmd = " ".join(result.argv)
    body = f"[bold]{cmd}[/bold]\n\n[bold]stdout[/bold]\n{result.stdout}\n\n[bold]stderr[/bold]\n{result.stderr}"
    border = "green" if result.returncode == 0 else "red"
    console.print(
        Panel(body, title=f"dev-run exit {result.returncode}", border_style=border)
    )


def _prompt_optional_dev_run(project_root: Path) -> None:
    console.print(
        "[dim]Dev-run allowlist: python/py/pytest, npm|pnpm|yarn (test|run|exec|start only), "
        "go/cargo/dotnet/uv/make/deno/bun (see dev_runner.py), pip show|list|check|freeze, "
        "poetry run <…>. No shell, no pipes, cwd is the project folder.[/dim]"
    )
    line = console.input(
        "[cyan]Run a dev command in this project? [Enter to skip] [/cyan]"
    ).strip()
    if not line:
        return
    try:
        parts = shlex.split(line, posix=os.name != "nt")
    except ValueError as e:
        console.print(f"[red]Could not parse command:[/red] {e}")
        return
    if not parts:
        return
    ok, msg = validate_dev_command(parts)
    if not ok:
        console.print(f"[red]Command not allowed:[/red] {msg}")
        return
    with console.status("[bold]Running dev command..."):
        result = run_dev_command(project_root, parts)
    _print_run_result(result)


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
    p.add_argument(
        "--no-dev-prompt",
        action="store_true",
        help="After the agent finishes, do not offer the optional dev-run prompt.",
    )
    return p.parse_args(argv)


def cmd_dev_run_main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="manager.py dev-run",
        description="Run an allowlisted development command in the project directory (no shell).",
    )
    parser.add_argument(
        "-p",
        "--project",
        type=Path,
        default=None,
        help="Project directory (cwd for the command). Default: MICRO_AGENT_PROJECT or cwd.",
    )
    parser.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        help="Command argv, typically after -- (example: -- python -m pytest -q)",
    )
    args = parser.parse_args(argv)
    cmd = list(args.cmd)
    while cmd and cmd[0] == "--":
        cmd.pop(0)
    if not cmd:
        parser.error(
            "Missing command. Example: python manager.py dev-run -p . -- python -m pytest -q"
        )
    project_root = _resolve_project_root(args.project)
    ok, msg = validate_dev_command(cmd)
    if not ok:
        console.print(f"[red]Command not allowed:[/red] {msg}")
        raise SystemExit(2)
    console.print(Panel(f"[bold]cwd[/bold] {project_root}\n[bold]cmd[/bold] {' '.join(cmd)}", title="dev-run"))
    result = run_dev_command(project_root, cmd)
    _print_run_result(result)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main(argv: list[str] | None = None) -> None:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    if argv_list and argv_list[0] == "dev-run":
        cmd_dev_run_main(argv_list[1:])
        return

    args = parse_args(argv_list)
    project_root = _resolve_project_root(args.project)

    structure = describe_project_tree(project_root)
    md_bundle, md_count = collect_project_markdown_docs(project_root)
    md_digest_for_engineer = md_bundle

    console.print(
        Panel(
            f"[bold]Project:[/bold] {project_root}\n"
            f"[bold]Markdown files loaded:[/bold] {md_count}\n\n"
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
            "Plan this project. When PROJECT MARKDOWN appears below, read it BEFORE you draft your own TODOs. "
            "Start your answer with a section titled exactly: \"## Alignment with existing notes\" that explains how "
            "your plan reflects those markdown documents and what is still missing or conflicting with the user request. "
            "After that section, output a structured Markdown TODO list; prefer items that name concrete relative paths.\n\n"
            f"User request:\n{user_request}\n\n"
            f"{_project_context_block(structure)}\n\n"
            f"{_markdown_docs_for_architect(md_bundle)}",
        )
    console.print(Panel(plan, title="Architect's Blueprint", border_style="yellow"))

    with console.status("[bold green]Dom is summarizing for the team..."):
        dom_summary = ai.ask(
            "dom",
            "In 2–4 short paragraphs, summarize how this project fits typical stack choices "
            "and what the team should watch for. User request:\n"
            f"{user_request}\n\nPlan:\n{plan}\n\n"
            f"Markdown files loaded from disk for this run: {md_count}.\n\n"
            f"{structure[:4500]}{'…' if len(structure) > 4500 else ''}\n\n"
            f"{_markdown_digest_block(md_bundle, limit=4500)}",
        )
    console.print(Panel(dom_summary, title="Dom's summary", border_style="green"))

    tasks = parse_plan_tasks(plan)
    if len(tasks) < 2:
        extra = extract_todo_lines_from_markdown(md_bundle, max_lines=MAX_TASKS_FROM_PLAN)
        seen_tasks = set(tasks)
        for line in extra:
            if line in seen_tasks:
                continue
            seen_tasks.add(line)
            tasks.append(line)
            if len(tasks) >= MAX_TASKS_FROM_PLAN:
                break
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
                markdown_digest=md_digest_for_engineer,
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
                code = _apply_fix(
                    ai,
                    review=review,
                    code=code,
                    structure=structure,
                    markdown_digest=md_digest_for_engineer,
                )
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

    if not args.no_dev_prompt:
        _prompt_optional_dev_run(project_root)


if __name__ == "__main__":
    main()
