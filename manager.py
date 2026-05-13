import re
from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel

from llm.provider import GeminiProvider

console = Console()

# Cap extracted TODO lines so one run does not fan out into dozens of API calls.
MAX_TASKS_FROM_PLAN = 12

_TASK_LINE = re.compile(
    r"^(?:[-*]|\d+\.)\s+(?:\[[ x]\]\s*)?(.+)$",
    re.IGNORECASE,
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


def save_to_file(filename, content):
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    console.print(f"[bold green]💾 Saved to {filename}[/bold green]")


@dataclass
class Artifact:
    task: str
    code: str
    review: str


def _engineer_for_task(
    ai: GeminiProvider,
    *,
    user_request: str,
    plan: str,
    task: str,
    dom_summary: str,
) -> str:
    prompt = (
        f"User request:\n{user_request}\n\n"
        f"Architect plan:\n{plan}\n\n"
        f"Project lead context (short):\n{dom_summary}\n\n"
        f"Implement ONLY this task from the plan. If the task implies multiple files, "
        f"include each file with a clear header or path comment before its code block.\n\n"
        f"Task:\n{task}"
    )
    return ai.ask("engineer", prompt)


def _review(ai: GeminiProvider, *, plan: str, task: str, code: str) -> str:
    return ai.ask(
        "reviewer",
        f"Task:\n{task}\n\nTarget Code:\n{code}\n\nOriginal Plan:\n{plan}",
    )


def _apply_fix(ai: GeminiProvider, *, review: str, code: str) -> str:
    return ai.ask(
        "engineer",
        f"Fix this code based on these review comments:\n{review}\n\nCode:\n{code}",
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


def main():
    ai = GeminiProvider()

    console.print(Panel("[bold magenta]Multi-Agent Coding System Active[/bold magenta]"))

    user_request = console.input("[bold cyan]What project are we building today? [/bold cyan]")

    with console.status("[bold yellow]Architect is planning..."):
        plan = ai.ask("architect", f"Plan this project: {user_request}")
    console.print(Panel(plan, title="Architect's Blueprint", border_style="yellow"))

    with console.status("[bold green]Dom is summarizing for the team..."):
        dom_summary = ai.ask(
            "dom",
            "In 2–4 short paragraphs, summarize how this project fits typical stack choices "
            f"and what the team should watch for. User request:\n{user_request}\n\nPlan:\n{plan}",
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
            )
        console.print(
            Panel(code, title=f"Engineer — task {idx}/{len(tasks)}", border_style="blue")
        )

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
                code = _apply_fix(ai, review=review, code=code)
            console.print(
                Panel(
                    code,
                    title=f"Refined code — task {idx}/{len(tasks)}",
                    border_style="green",
                )
            )

        artifacts.append(Artifact(task=task, code=code, review=review))

    final_output = _format_final_output(user_request, plan, dom_summary, artifacts)
    save_to_file("final_output.txt", final_output)


if __name__ == "__main__":
    main()
