"""Project folder layout and safe file writes for the CLI agent."""

from __future__ import annotations

import re
from pathlib import Path

_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".svn",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        "dist",
        "build",
        ".idea",
        ".cursor",
        ".eggs",
        "eggs",
    }
)

_MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})

# Lines that look like TODO / checklist items inside markdown bodies.
_MD_TASK_LINE = re.compile(
    r"^(?:[-*]|\d+\.)\s+(?:\[[ x]\]\s*)?(.+)$",
    re.IGNORECASE,
)


def _relative_path_is_ignored(rel: Path) -> bool:
    parts = rel.parts
    if any(p in _SKIP_DIR_NAMES for p in parts):
        return True
    if any(p.endswith(".egg-info") for p in parts):
        return True
    return False

# Single-token fence info that is only a path, e.g. ```src/main.py
_FENCE_INFO_PATH = re.compile(
    r"^[\w./\\-]+\.[A-Za-z0-9]{1,12}$",
)


def _looks_like_rel_path(token: str) -> bool:
    t = token.strip().replace("\\", "/")
    if not t or " " in t or ".." in Path(t).parts or t.startswith("/"):
        return False
    if "/" in t or "\\" in token:
        return True
    return bool(_FENCE_INFO_PATH.match(t))


def _path_from_fence_info(info: str) -> str | None:
    """Handle ```path.ext or ```python path/to/file.py."""
    info = info.strip()
    if not info:
        return None
    if _looks_like_rel_path(info):
        return info.replace("\\", "/")
    parts = info.split()
    if len(parts) >= 2 and _looks_like_rel_path(parts[-1]):
        return parts[-1].replace("\\", "/")
    return None


def _strip_file_marker_prefix(body: str) -> tuple[str | None, str]:
    """If the first line is '# file:' or '// file:', return (path, rest)."""
    text = body.lstrip("\n")
    if not text:
        return None, body
    first_line, sep, rest = text.partition("\n")
    m = re.match(r"^(?:#|//)\s*file:\s*(.+)$", first_line.strip())
    if not m:
        return None, body
    path = m.group(1).strip().replace("\\", "/")
    content = rest.lstrip("\n") if sep else ""
    return path, content


def describe_project_tree(
    root: Path,
    *,
    max_files: int = 250,
    max_depth: int = 10,
) -> str:
    """Return a bounded, sorted tree listing for LLM context."""
    root = root.resolve()
    if not root.is_dir():
        return f"(Project path is not a directory: {root})"

    lines: list[str] = [f"Project root: {root}", ""]
    count = 0

    def walk(current: Path, depth: int, prefix: str) -> None:
        nonlocal count
        if count >= max_files or depth > max_depth:
            return
        try:
            entries = sorted(
                current.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except OSError:
            lines.append(f"{prefix}[inaccessible]")
            return

        for p in entries:
            if count >= max_files:
                lines.append(f"{prefix}… (truncated, max_files={max_files})")
                return
            name = p.name
            if name in _SKIP_DIR_NAMES or name.endswith(".egg-info"):
                continue
            rel = p.relative_to(root)
            if _relative_path_is_ignored(rel):
                continue
            if p.is_dir():
                lines.append(f"{prefix}{name}/")
                count += 1
                walk(p, depth + 1, prefix + "  ")
            else:
                lines.append(f"{prefix}{name}")
                count += 1

    walk(root, 0, "")
    if len(lines) <= 2:
        lines.append("(empty or only ignored entries)")
    return "\n".join(lines)


def _markdown_sort_key(path: Path) -> tuple[int, str]:
    """Prefer README / TODO-style docs first, then path."""
    n = path.name.lower()
    pri = 0
    if n == "readme.md":
        pri -= 5
    elif "todo" in n:
        pri -= 4
    elif n in ("agents.md", "contributing.md"):
        pri -= 3
    elif "spec" in n or n.endswith("_spec.md"):
        pri -= 2
    return (pri, str(path).lower())


def collect_project_markdown_docs(
    root: Path,
    *,
    max_files: int = 32,
    max_chars_per_file: int = 14_000,
    max_total_chars: int = 42_000,
) -> tuple[str, int]:
    """
    Read markdown files under root (skipping ignored dirs) for LLM / TODO context.
    Returns (bundle_text, number_of_files_included).
    """
    root = root.resolve()
    if not root.is_dir():
        return ("(Project path is not a directory.)\n", 0)

    candidates: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        if _relative_path_is_ignored(rel):
            continue
        suf = p.suffix.lower()
        if suf not in _MARKDOWN_SUFFIXES:
            continue
        candidates.append(p)

    candidates.sort(key=_markdown_sort_key)
    candidates = candidates[:max_files]

    parts: list[str] = []
    total = 0
    used = 0
    for p in candidates:
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = p.relative_to(root).as_posix()
        header = f"\n---\n### Markdown file: {rel}\n\n"
        chunk = raw
        if len(chunk) > max_chars_per_file:
            chunk = chunk[:max_chars_per_file] + "\n\n… (file truncated)\n"

        block = header + chunk
        remaining = max_total_chars - total
        if remaining <= len(header) + 32:
            parts.append(
                "\n---\n… (markdown bundle truncated; more matching files may exist on disk)\n"
            )
            break
        if len(block) > remaining:
            keep = max(0, remaining - len(header) - 64)
            chunk = chunk[:keep] + "\n… (truncated to budget)\n"
            block = header + chunk

        parts.append(block)
        total += len(block)
        used += 1

    if not parts:
        return ("(No markdown files found under project root.)\n", 0)
    body = "".join(parts).lstrip("\n")
    return (body + "\n", used)


def extract_todo_lines_from_markdown(markdown_bundle: str, max_lines: int = 20) -> list[str]:
    """Pull checklist / bullet lines from bundled markdown (e.g. TODO.md)."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in markdown_bundle.splitlines():
        line = raw.strip()
        if len(line) < 4:
            continue
        if line.startswith("#"):
            continue
        if line.startswith(">"):
            line = line.lstrip("> ").strip()
        m = _MD_TASK_LINE.match(line)
        if not m:
            continue
        text = m.group(1).strip()
        if len(text) < 4 or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= max_lines:
            break
    return out


def resolve_safe_path(root: Path, rel: str) -> Path:
    """Resolve rel under root; reject traversal outside root."""
    rel_norm = rel.strip().replace("\\", "/")
    if not rel_norm or rel_norm.startswith("/"):
        raise ValueError(f"Invalid relative path: {rel!r}")
    parts = Path(rel_norm).parts
    if ".." in parts:
        raise ValueError(f"Path must not contain '..': {rel!r}")
    root_r = root.resolve()
    out = (root_r / rel_norm).resolve()
    try:
        out.relative_to(root_r)
    except ValueError as e:
        raise ValueError(f"Path escapes project root: {rel!r}") from e
    return out


def iter_fenced_blocks(markdown: str):
    """Yield (fence_info_line, body) for each ``` … ``` block."""
    lines = markdown.splitlines(keepends=True)
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.startswith("```"):
            opener = line.rstrip("\n\r")
            info = opener[3:].strip()
            i += 1
            body_chunks: list[str] = []
            while i < n and not lines[i].startswith("```"):
                body_chunks.append(lines[i])
                i += 1
            if i < n and lines[i].startswith("```"):
                i += 1
            yield info, "".join(body_chunks)
        else:
            i += 1


def guess_block_path(fence_info: str, body: str) -> str | None:
    from_fence = _path_from_fence_info(fence_info)
    if from_fence:
        return from_fence
    marker_path, _ = _strip_file_marker_prefix(body)
    if marker_path and _looks_like_rel_path(marker_path):
        return marker_path
    return None


def write_files_from_agent_output(
    root: Path,
    markdown: str,
) -> tuple[list[str], list[str]]:
    """
    Parse fenced blocks and write files under root.
    Returns (written_rel_paths, error_messages).
    """
    written: list[str] = []
    errors: list[str] = []
    root = root.resolve()

    for fence_info, body in iter_fenced_blocks(markdown):
        rel = guess_block_path(fence_info, body)
        if not rel:
            continue
        marker_path, rest = _strip_file_marker_prefix(body)
        rel_norm = rel.replace("\\", "/")
        if marker_path and marker_path.replace("\\", "/") == rel_norm:
            content = rest
        else:
            content = body
        content = content.rstrip("\n")
        if content and not content.endswith("\n"):
            content += "\n"
        try:
            dest = resolve_safe_path(root, rel)
        except ValueError as e:
            errors.append(str(e))
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8", newline="\n")
            written.append(rel.replace("\\", "/"))
        except OSError as e:
            errors.append(f"{rel}: {e}")

    return written, errors
