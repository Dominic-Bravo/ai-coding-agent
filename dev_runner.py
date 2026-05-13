"""Allowlisted local dev commands (tests, builds, linters) — no shell, cwd = project root."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# First argv[0] after basename / .exe strip (lowercase).
_ALLOWED_ROOT = frozenset(
    {
        "python",
        "py",
        "pytest",
        "pip",
        "pip3",
        "npm",
        "pnpm",
        "yarn",
        "node",
        "cargo",
        "go",
        "uv",
        "dotnet",
        "gradle",
        "mvn",
        "ruff",
        "black",
        "mypy",
        "flake8",
        "tox",
        "make",
        "poetry",
        "deno",
        "bun",
    }
)

# Disallow shell / download / remote helpers as the invoked program.
_FORBIDDEN_ROOT = frozenset(
    {
        "cmd",
        "cmd.exe",
        "powershell",
        "pwsh",
        "sh",
        "bash",
        "zsh",
        "fish",
        "wsl",
        "curl",
        "wget",
        "ssh",
        "scp",
        "git",
    }
)

# Block obvious shell injection / chaining in any argument.
_FORBIDDEN_SUBSTRINGS = (
    "|",
    "||",
    "&&",
    ";",
    "\n",
    "\r",
    "`",
    "$(",
    "${",
    ">%",
    " 2>",
    "\x00",
)

_PACKAGE_RUNNERS = frozenset({"npm", "pnpm", "yarn"})
_PACKAGE_SUB = frozenset({"test", "run", "exec", "start"})

_PIP_READ_ONLY = frozenset({"show", "list", "check", "freeze"})


@dataclass
class RunResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str


def _root_name(argv0: str) -> str:
    name = Path(argv0).name
    lower = name.lower()
    if lower.endswith(".exe"):
        name = name[:-4]
    return name.lower()


def _has_forbidden_tokens(argv: list[str]) -> str | None:
    joined = " ".join(argv)
    for bad in _FORBIDDEN_SUBSTRINGS:
        if bad in joined:
            return f"disallowed token or sequence: {bad!r}"
    for a in argv:
        if re.search(r"[<>]", a):
            return "shell redirection characters are not allowed"
    return None


def _npm_like_ok(root: str, argv: list[str]) -> str | None:
    if len(argv) < 2:
        return f"{root} requires a subcommand such as test, run, exec, or start"
    sub = argv[1].lower()
    if sub not in _PACKAGE_SUB:
        return f"{root} only allows subcommands: {', '.join(sorted(_PACKAGE_SUB))}"
    return None


def _pip_ok(argv: list[str]) -> str | None:
    if len(argv) < 2:
        return "pip requires a subcommand (show, list, check, freeze only)"
    if argv[1].lower() not in _PIP_READ_ONLY:
        return "pip is limited to read-only-ish commands: show, list, check, freeze"
    return None


def _go_ok(argv: list[str]) -> str | None:
    if len(argv) < 2:
        return "go requires a subcommand (test, run, vet, build, mod, generate)"
    sub = argv[1].lower()
    allowed = frozenset({"test", "run", "vet", "build", "mod", "generate"})
    if sub not in allowed:
        return f"go only allows: {', '.join(sorted(allowed))}"
    return None


def _cargo_ok(argv: list[str]) -> str | None:
    if len(argv) < 2:
        return "cargo requires a subcommand (test, run, build, check, clippy, fmt)"
    sub = argv[1].lower()
    allowed = frozenset({"test", "run", "build", "check", "clippy", "fmt"})
    if sub not in allowed:
        return f"cargo only allows: {', '.join(sorted(allowed))}"
    return None


def _dotnet_ok(argv: list[str]) -> str | None:
    if len(argv) < 2:
        return "dotnet requires a subcommand (test, build, run, watch)"
    sub = argv[1].lower()
    allowed = frozenset({"test", "build", "run", "watch"})
    if sub not in allowed:
        return f"dotnet only allows: {', '.join(sorted(allowed))}"
    return None


def _uv_ok(argv: list[str]) -> str | None:
    if len(argv) < 2:
        return "uv requires a subcommand (run, sync, lock, pip)"
    sub = argv[1].lower()
    allowed = frozenset({"run", "sync", "lock", "pip"})
    if sub not in allowed:
        return f"uv only allows: {', '.join(sorted(allowed))}"
    if sub == "pip":
        if len(argv) < 3:
            return "uv pip requires a pip subcommand (show, list, check, freeze only)"
        pip_sub = argv[2].lower()
        if pip_sub not in _PIP_READ_ONLY:
            return "uv pip is limited to: show, list, check, freeze"
    return None


def _make_ok(argv: list[str]) -> str | None:
    if len(argv) < 2:
        return "make requires an explicit target (e.g. test, lint, build, check)"
    tgt = argv[1].lower()
    allowed = frozenset({"test", "lint", "build", "check"})
    if tgt not in allowed:
        return f"make only allows targets: {', '.join(sorted(allowed))}"
    return None


def _deno_ok(argv: list[str]) -> str | None:
    if len(argv) < 2:
        return "deno requires a subcommand (test, run, fmt, lint)"
    sub = argv[1].lower()
    allowed = frozenset({"test", "run", "fmt", "lint"})
    if sub not in allowed:
        return f"deno only allows: {', '.join(sorted(allowed))}"
    return None


def _bun_ok(argv: list[str]) -> str | None:
    if len(argv) < 2:
        return "bun requires a subcommand (test, run, x)"
    sub = argv[1].lower()
    allowed = frozenset({"test", "run", "x"})
    if sub not in allowed:
        return f"bun only allows: {', '.join(sorted(allowed))}"
    return None


def _python_ok(argv: list[str]) -> str | None:
    for i, a in enumerate(argv):
        if a == "-c":
            return "python -c is not allowlisted (run a file or use -m unittest/pytest)"
        if a in ("-m",) and i + 1 < len(argv):
            mod = argv[i + 1].lower()
            allowed_mod_prefixes = (
                "pytest",
                "unittest",
                "pip",
                "build",
                "compileall",
                "venv",
            )
            if not any(mod == p or mod.startswith(p + ".") for p in allowed_mod_prefixes):
                return f"python -m {mod!r} is not on the allowlist for this tool"
    return None


def validate_dev_command(argv: list[str], _depth: int = 0) -> tuple[bool, str]:
    """
    Return (ok, message). message is empty when ok, else a human-readable reason.
    """
    if _depth > 4:
        return False, "nested command depth exceeded"

    if not argv:
        return False, "empty command"
    tok = _has_forbidden_tokens(argv)
    if tok:
        return False, tok

    root = _root_name(argv[0])
    if root in _FORBIDDEN_ROOT:
        return False, f"executable {root!r} is not allowlisted for dev-run"
    if root not in _ALLOWED_ROOT:
        return False, f"executable {root!r} is not in the dev allowlist"

    if root == "poetry":
        if len(argv) < 3 or argv[1].lower() != "run":
            return False, "poetry is limited to: poetry run <allowlisted command>"
        return validate_dev_command(argv[2:], _depth + 1)

    if root in ("python", "py"):
        err = _python_ok(argv)
        if err:
            return False, err
    if root in ("pip", "pip3"):
        err = _pip_ok(argv)
        if err:
            return False, err
    if root in _PACKAGE_RUNNERS:
        err = _npm_like_ok(root, argv)
        if err:
            return False, err
    if root == "go":
        err = _go_ok(argv)
        if err:
            return False, err
    if root == "cargo":
        err = _cargo_ok(argv)
        if err:
            return False, err
    if root == "dotnet":
        err = _dotnet_ok(argv)
        if err:
            return False, err
    if root == "uv":
        err = _uv_ok(argv)
        if err:
            return False, err
    if root == "make":
        err = _make_ok(argv)
        if err:
            return False, err
    if root == "deno":
        err = _deno_ok(argv)
        if err:
            return False, err
    if root == "bun":
        err = _bun_ok(argv)
        if err:
            return False, err

    if len(argv) > 48:
        return False, "too many arguments"

    return True, ""


def run_dev_command(
    project_root: Path,
    argv: list[str],
    *,
    timeout_sec: int = 300,
    max_capture_chars: int = 200_000,
) -> RunResult:
    """
    Run argv with cwd=project_root, shell=False. Caller must validate first.
    """
    cwd = project_root.resolve()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            shell=False,
            env=os.environ.copy(),
        )
        out = proc.stdout or ""
        err = proc.stderr or ""
        code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or "" if isinstance(exc.stdout, str) else ""
        err = (exc.stderr or "" if isinstance(exc.stderr, str) else "") + "\n[timeout]\n"
        code = 124
    if len(out) > max_capture_chars:
        out = out[:max_capture_chars] + "\n… (stdout truncated)\n"
    if len(err) > max_capture_chars:
        err = err[:max_capture_chars] + "\n… (stderr truncated)\n"
    return RunResult(argv=argv, returncode=code, stdout=out, stderr=err)
