from __future__ import annotations

import getpass
import os
import time
from typing import Protocol, runtime_checkable

import anthropic
from dotenv import load_dotenv
from openai import APIConnectionError, APITimeoutError, APIStatusError, OpenAI, RateLimitError
from rich.console import Console
from rich.panel import Panel

from llm.errors import LLMRequestError

load_dotenv()

_DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
_DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
_DEFAULT_ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"
_MAX_RETRIES = 6
_BASE_DELAY_SEC = 1.0
_MAX_DELAY_SEC = 30.0

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _is_retryable_openai_error(exc: BaseException) -> bool:
    if isinstance(exc, (APIConnectionError, APITimeoutError, RateLimitError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code in (408, 429, 500, 502, 503, 504)
    return False


def _format_openai_failure(exc: BaseException) -> str:
    lines: list[str] = []
    if isinstance(exc, RateLimitError) or (
        isinstance(exc, APIStatusError) and exc.status_code == 429
    ):
        lines.extend(
            [
                "[bold]Rate limit or quota (HTTP 429)[/bold]",
                "",
                "What went wrong: the provider refused this request because a [bold]rate limit[/bold] or "
                "[bold]usage quota[/bold] was hit. On Google Gemini this often appears as free-tier "
                "limits per minute or per day.",
                "",
                "What you can do:",
                "- Wait for the cooldown (the provider message may say how many seconds).",
                "- Open your provider’s console and check billing, plan, and quota.",
                "- Use a different model (env vars GEMINI_MODEL, OPENAI_MODEL, or ANTHROPIC_MODEL).",
                "- Run this tool again and pick another provider at the start (OpenAI / Claude / Gemini).",
            ]
        )
    elif isinstance(exc, APIStatusError) and exc.status_code == 401:
        lines.extend(
            [
                "[bold]Authentication failed (HTTP 401)[/bold]",
                "",
                "Check that your API key is correct and active for the provider you selected.",
            ]
        )
    elif isinstance(exc, APIStatusError):
        lines.append(f"[bold]HTTP {exc.status_code}[/bold] from the model API.")
    else:
        lines.append("[bold]Request to the model API failed.[/bold]")

    lines.extend(["", "[dim]Technical detail (truncated):[/dim]", str(exc)[:2500]])
    return "\n".join(lines)


def _is_retryable_anthropic_error(exc: BaseException) -> bool:
    if isinstance(exc, anthropic.RateLimitError):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code in (408, 429, 500, 502, 503, 504)
    if isinstance(exc, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return True
    return False


def _format_anthropic_failure(exc: BaseException) -> str:
    lines: list[str] = []
    if isinstance(exc, anthropic.RateLimitError) or (
        isinstance(exc, anthropic.APIStatusError) and getattr(exc, "status_code", None) == 429
    ):
        lines.extend(
            [
                "[bold]Rate limit or quota (HTTP 429)[/bold]",
                "",
                "Anthropic rate-limited this request or your usage tier quota was exceeded.",
                "",
                "What you can do: wait, check the Anthropic console for usage/limits, or set ANTHROPIC_MODEL to another Claude model.",
            ]
        )
    elif isinstance(exc, anthropic.APIStatusError) and exc.status_code == 401:
        lines.append("[bold]Invalid Anthropic API key (401).[/bold]")
    else:
        lines.append("[bold]Anthropic API error.[/bold]")
    lines.extend(["", "[dim]Technical detail (truncated):[/dim]", str(exc)[:2500]])
    return "\n".join(lines)


@runtime_checkable
class AgentLLMProvider(Protocol):
    model: str

    def get_role_instructions(self, role_name: str) -> str: ...
    def ask(self, role: str, task_prompt: str) -> str: ...
    def get_response(self, user_prompt: str) -> str: ...


class RoleInstructionsMixin:
    """Shared persona / role system prompts."""

    def get_role_instructions(self, role_name: str) -> str:
        aliases = {
            "lead engineer": "engineer",
            "lead_engineer": "engineer",
        }
        key = (role_name or "").strip().lower()
        key = aliases.get(key, key)

        roles = {
            "architect": (
                "You are the Architect Agent. Your job is to take a user request and "
                "break it down into a list of required files and folders. "
                "When the user message includes a PROJECT MARKDOWN section, read it before your own plan: "
                "those files often contain specs, TODO lists, or notes that should shape the work. "
                "Follow any instruction in the user message about section titles (for example, "
                "an \"Alignment with existing notes\" opener). "
                "Output only a structured TODO list in Markdown after that opener when requested."
            ),
            "engineer": (
                "You are the Lead Engineer. "
                "Your technology stack is STRICTLY determined by the Architect's plan. "
                "You MUST carefully analyze the Architect's instructions before generating any code. "
                "Only use the programming languages, frameworks, libraries, architectures, tools, "
                "and design patterns explicitly defined in the plan. "
                "Do NOT introduce your own preferred technologies, alternatives, or assumptions. "
                "Your role is to implement the system exactly as specified. "
                "Generate clean, production-ready, well-structured code with clear inline comments "
                "and maintainable architecture. "
                "Focus on correctness, scalability, readability, and modularity. "
                "If the plan is unclear or missing implementation details, infer conservatively "
                "without changing the intended stack or architecture. "
                "Adapt your coding style, abstractions, and implementation depth based on the project type, "
                "complexity, and role requirements. "
                "You should behave like a specialized fine-tuned engineer for the exact stack "
                "and architecture provided in the Architect's plan."
            ),
            "reviewer": (
                "You are the Code Reviewer. Your job is to look for bugs, security "
                "vulnerabilities, and PEP8 compliance in the provided code."
            ),
            "dom": (
                "You are Dominic Ian Bravo (Dom). You oversee the project. "
                "You communicate with the user about projects like AuthSocials and "
                "your tech stack. Mention Angel Mae Jaban if personal topics arise."
            ),
        }
        return roles.get(key, roles["dom"])


class OpenAICompatProvider(RoleInstructionsMixin):
    """OpenAI Chat Completions API (used for OpenAI.com and Google Gemini OpenAI-compatible endpoint)."""

    def __init__(self, *, api_key: str, base_url: str | None, model: str) -> None:
        kw: dict = {"api_key": api_key}
        if base_url:
            kw["base_url"] = base_url
        self.client = OpenAI(**kw)
        self.model = model.strip()

    def _chat_completion_create(self, messages: list[dict], *, temperature: float):
        delay = _BASE_DELAY_SEC
        for attempt in range(_MAX_RETRIES):
            try:
                return self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                )
            except Exception as e:
                if not _is_retryable_openai_error(e):
                    raise LLMRequestError(_format_openai_failure(e)) from e
                if attempt == _MAX_RETRIES - 1:
                    raise LLMRequestError(_format_openai_failure(e)) from e
                time.sleep(min(delay, _MAX_DELAY_SEC))
                delay = min(delay * 2.0, _MAX_DELAY_SEC)
        raise RuntimeError("unreachable")

    def ask(self, role: str, task_prompt: str) -> str:
        system_instruction = self.get_role_instructions(role)
        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": task_prompt},
        ]
        response = self._chat_completion_create(messages, temperature=0.2)
        content = response.choices[0].message.content
        if content is None:
            return ""
        return content

    def get_response(self, user_prompt: str) -> str:
        my_details = """
        I am Dominic Ian Bravo (Dom), a Python Dev (Django, FastAPI, React Native).
        Working on: 'AuthSocials' and E-commerce backends.
        Tools: uv, Celery, Redis.
        Personal: My girlfriend is Angel Mae Jaban.
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Dom. Use 'I/me/my'. Character Data: "
                    f"{my_details}. Rule: Talk tech. If asked about personal life, only mention "
                    "Angel Mae Jaban. Refuse other outside topics. No code blocks for now."
                ),
            },
            {"role": "user", "content": user_prompt},
        ]
        try:
            response = self._chat_completion_create(messages, temperature=0.3)
            content = response.choices[0].message.content
            return content if content is not None else ""
        except LLMRequestError as e:
            return f"Error: {e}"


class GeminiProvider(OpenAICompatProvider):
    """Google Gemini via OpenAI-compatible endpoint (legacy entry point for tests)."""

    def __init__(self) -> None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set in environment variables.")
        super().__init__(
            api_key=api_key,
            base_url=_GEMINI_BASE_URL,
            model=(os.getenv("GEMINI_MODEL") or _DEFAULT_GEMINI_MODEL).strip(),
        )


class AnthropicClaudeProvider(RoleInstructionsMixin):
    """Anthropic Messages API."""

    def __init__(self, *, api_key: str, model: str) -> None:
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model.strip()

    def _messages_create(self, *, system: str, user_text: str, temperature: float) -> str:
        delay = _BASE_DELAY_SEC
        for attempt in range(_MAX_RETRIES):
            try:
                msg = self.client.messages.create(
                    model=self.model,
                    max_tokens=8192,
                    temperature=temperature,
                    system=system,
                    messages=[{"role": "user", "content": user_text}],
                )
                parts: list[str] = []
                for block in msg.content:
                    if hasattr(block, "text"):
                        parts.append(block.text)
                return "".join(parts)
            except Exception as e:
                if not _is_retryable_anthropic_error(e):
                    raise LLMRequestError(_format_anthropic_failure(e)) from e
                if attempt == _MAX_RETRIES - 1:
                    raise LLMRequestError(_format_anthropic_failure(e)) from e
                time.sleep(min(delay, _MAX_DELAY_SEC))
                delay = min(delay * 2.0, _MAX_DELAY_SEC)
        raise RuntimeError("unreachable")

    def ask(self, role: str, task_prompt: str) -> str:
        system = self.get_role_instructions(role)
        return self._messages_create(system=system, user_text=task_prompt, temperature=0.2)

    def get_response(self, user_prompt: str) -> str:
        my_details = (
            "I am Dominic Ian Bravo (Dom), a Python Dev (Django, FastAPI, React Native). "
            "Working on: 'AuthSocials' and E-commerce backends. Tools: uv, Celery, Redis. "
            "Personal: My girlfriend is Angel Mae Jaban."
        )
        system = (
            f"You are Dom. Use 'I/me/my'. Character Data: {my_details}. Rule: Talk tech. "
            "If asked about personal life, only mention Angel Mae Jaban. Refuse other outside topics. "
            "No code blocks for now."
        )
        try:
            return self._messages_create(system=system, user_text=user_prompt, temperature=0.3)
        except LLMRequestError as e:
            return f"Error: {e}"


def _prompt_secret(console: Console, prompt: str) -> str:
    console.print(prompt)
    return getpass.getpass("API key (hidden): ").strip()


def create_llm_provider(
    console: Console,
    *,
    provider_override: str | None = None,
) -> AgentLLMProvider:
    """
    Interactive or env-driven LLM selection.

    Env:
      MICRO_AGENT_PROVIDER = gemini | openai | anthropic
      GEMINI_API_KEY, GEMINI_MODEL
      OPENAI_API_KEY, OPENAI_MODEL
      ANTHROPIC_API_KEY, ANTHROPIC_MODEL
    """
    load_dotenv()
    choice = (provider_override or os.getenv("MICRO_AGENT_PROVIDER") or "").strip().lower()

    if choice not in ("gemini", "openai", "anthropic"):
        console.print(
            Panel(
                "[bold]Choose an LLM provider[/bold] (saved for this run only unless you use .env)\n\n"
                "[bold]1[/bold]  Google [cyan]Gemini[/cyan] — needs GEMINI_API_KEY (or paste when asked)\n"
                "[bold]2[/bold]  OpenAI [cyan]ChatGPT API[/cyan] — needs OPENAI_API_KEY\n"
                "[bold]3[/bold]  [cyan]Anthropic Claude[/cyan] — needs ANTHROPIC_API_KEY\n\n"
                "[dim]Tip: set MICRO_AGENT_PROVIDER and the matching *_API_KEY in the environment "
                "to skip this menu.[/dim]",
                title="LLM provider",
                border_style="blue",
            )
        )
        raw = console.input("[cyan]Enter 1, 2, or 3 [default: 1]: [/cyan]").strip() or "1"
        choice = {"1": "gemini", "2": "openai", "3": "anthropic"}.get(raw, "gemini")

    if choice == "gemini":
        key = (os.getenv("GEMINI_API_KEY") or "").strip()
        if not key:
            key = _prompt_secret(console, "[yellow]Gemini: paste your Google AI Studio API key.[/yellow]")
        if not key:
            raise SystemExit("No API key provided for Gemini.")
        model = (os.getenv("GEMINI_MODEL") or _DEFAULT_GEMINI_MODEL).strip()
        return OpenAICompatProvider(api_key=key, base_url=_GEMINI_BASE_URL, model=model)

    if choice == "openai":
        key = (os.getenv("OPENAI_API_KEY") or "").strip()
        if not key:
            key = _prompt_secret(console, "[yellow]OpenAI: paste your API key from platform.openai.com[/yellow]")
        if not key:
            raise SystemExit("No API key provided for OpenAI.")
        model = (os.getenv("OPENAI_MODEL") or _DEFAULT_OPENAI_MODEL).strip()
        return OpenAICompatProvider(api_key=key, base_url=None, model=model)

    if choice == "anthropic":
        key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
        if not key:
            key = _prompt_secret(console, "[yellow]Anthropic: paste your API key from console.anthropic.com[/yellow]")
        if not key:
            raise SystemExit("No API key provided for Anthropic.")
        model = (os.getenv("ANTHROPIC_MODEL") or _DEFAULT_ANTHROPIC_MODEL).strip()
        return AnthropicClaudeProvider(api_key=key, model=model)

    raise SystemExit(f"Unknown provider: {choice!r}")
