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
            if any(part in _SKIP_DIR_NAMES for part in rel.parts):
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
