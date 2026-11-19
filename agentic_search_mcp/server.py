"""MCP server exposing three filesystem search tools: read, glob, and grep.

All paths are resolved relative to a single search root, which is set with the
``AGENTIC_SEARCH_ROOT`` environment variable (defaults to the process working
directory). Paths that escape the root are rejected.
"""

from __future__ import annotations

import difflib
import os
import re
from fnmatch import fnmatch
from pathlib import Path

try:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as Server
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as Server
    from mcp.server.fastmcp.exceptions import ToolError

# Directories skipped during recursive searches (grep/glob).
DEFAULT_EXCLUDED_DIRS = frozenset(
    {".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", "dist", "build"}
)

mcp = Server("agentic-search")


def _root() -> Path:
    """Return the resolved search root."""
    return Path(os.environ.get("AGENTIC_SEARCH_ROOT", os.getcwd())).expanduser().resolve()


def _resolve(path: str) -> Path:
    """Resolve *path* against the search root, rejecting paths that escape it."""
    root = _root()
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    if not candidate.is_relative_to(root):
        raise ToolError(f"Path escapes the search root ({root}): {path!r}")
    return candidate


def _display(path: Path) -> str:
    """Return a root-relative, forward-slash path for output."""
    try:
        return path.resolve().relative_to(_root()).as_posix()
    except ValueError:
        return path.as_posix()


def _is_binary(path: Path) -> bool:
    """Cheap binary detection: look for a NUL byte in the first 8 KiB."""
    with path.open("rb") as handle:
        return b"\0" in handle.read(8192)


def _should_skip(path: Path, excluded_dirs: frozenset[str]) -> bool:
    return any(part in excluded_dirs for part in path.parts)


def _suggest_paths(path: str, limit: int = 3) -> str:
    """Return the closest existing file paths to *path*, for self-correction."""
    target = str(Path(path)).replace("\\", "/").removeprefix("./").casefold()
    scored: list[tuple[float, str]] = []
    for candidate in _root().rglob("*"):
        if not candidate.is_file() or _should_skip(candidate, DEFAULT_EXCLUDED_DIRS):
            continue
        display = _display(candidate)
        folded = display.casefold()
        matcher = difflib.SequenceMatcher(None, target, folded)
        if matcher.real_quick_ratio() < 0.6 or matcher.quick_ratio() < 0.6:
            continue
        score = matcher.ratio()
        if score >= 0.6:
            scored.append((score, display))
    if not scored:
        return "Use glob to list matching files."
    best = sorted(scored, reverse=True)[:limit]
    return "Closest files: " + ", ".join(name for _, name in best)


@mcp.tool()
def read(path: str, offset: int = 0, limit: int = 2000) -> str:
    """Read a text file and return numbered lines.

    Args:
        path: File path, absolute or relative to the search root.
        offset: Zero-based line number to start from (default 0).
        limit: Maximum number of lines to return (default 2000).
    """
    if offset < 0:
        raise ToolError("offset must be >= 0")
    if limit < 1:
        raise ToolError("limit must be >= 1")

    target = _resolve(path)
    if not target.exists():
        raise ToolError(f"No such file: {path}. {_suggest_paths(path)}")
    if not target.is_file():
        raise ToolError(f"Not a file: {path} (use glob to list directories)")
    if _is_binary(target):
        raise ToolError(f"Refusing to read binary file: {path}")

    text = target.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    total = len(lines)
    selected = lines[offset : offset + limit]
    width = len(str(offset + len(selected)))
    body = "\n".join(f"{offset + index:>{width}}: {line}" for index, line in enumerate(selected))
    header = f"{_display(target)} — lines {offset}-{offset + len(selected) - 1} of {total}"
    return f"{header}\n{body}" if body else f"{header}\n(no lines in range)"


@mcp.tool()
def glob(pattern: str, path: str = ".", max_results: int = 1000) -> list[str]:
    """Find files and directories matching a glob pattern.

    Args:
        pattern: A pathlib-style glob, e.g. ``**/*.py`` or ``src/**/*.ts``.
        path: Directory to search within (absolute or root-relative, default root).
        max_results: Cap on returned matches (default 1000).
    """
    if max_results < 1:
        raise ToolError("max_results must be >= 1")

    base = _resolve(path)
    if not base.exists():
        raise ToolError(f"No such directory: {path}")
    if not base.is_dir():
        raise ToolError(f"Not a directory: {path}")

    matches: list[str] = []
    for candidate in sorted(base.glob(pattern)):
        if _should_skip(candidate, DEFAULT_EXCLUDED_DIRS):
            continue
        suffix = "/" if candidate.is_dir() else ""
        matches.append(_display(candidate) + suffix)
        if len(matches) >= max_results:
            break
    return matches


@mcp.tool()
def grep(
    pattern: str,
    path: str = ".",
    glob_filter: str | None = None,
    literal: bool = False,
    ignore_case: bool = False,
    max_results: int = 100,
) -> list[str]:
    r"""Search file contents with a regular expression (or a literal string).

    ``pattern`` is a Python ``re`` regular expression matched against each line
    with ``re.search`` -- it is not a shell grep command. Use ``|`` to combine
    alternatives, ``.*`` for wildcards, and groups/quantifiers such as
    ``(foo|bar)`` or ``\w+``. ``\|`` matches a literal pipe character, so do
    not escape ``|`` to mean "or" (GNU grep basic-regex syntax is not used).
    For example::

        grep(pattern="def (load|save)_config|class .*Settings|TODO.*(refactor|migrate)", glob_filter="*.py")

    Set ``literal=True`` to match plain text with no regex interpretation. Use
    ``ignore_case`` for case-insensitive matching and ``max_results`` to cap
    output; there is no shell pipeline to pipe into ``head``.

    Args:
        pattern: Regular expression (Python ``re`` syntax), or literal text
            when ``literal`` is true. Combine alternatives with unescaped ``|``.
        path: File or directory to search (absolute or root-relative, default root).
        glob_filter: Optional filename filter, e.g. ``*.py``.
        literal: Treat ``pattern`` as plain text instead of a regex (default false).
        ignore_case: Case-insensitive matching (default false).
        max_results: Cap on returned matches (default 100).
    """
    if max_results < 1:
        raise ToolError("max_results must be >= 1")

    flags = re.IGNORECASE if ignore_case else 0
    needle = re.escape(pattern) if literal else pattern
    try:
        regex = re.compile(needle, flags)
    except re.error as exc:
        raise ToolError(f"Invalid regular expression: {exc}") from exc

    target = _resolve(path)
    if not target.exists():
        raise ToolError(f"No such path: {path}")

    if target.is_file():
        files = [target]
    elif target.is_dir():
        files = [candidate for candidate in target.rglob("*") if candidate.is_file()]
    else:
        raise ToolError(f"Unsupported path type: {path}")

    results: list[str] = []
    for file in sorted(files):
        if len(results) >= max_results:
            break
        if _should_skip(file, DEFAULT_EXCLUDED_DIRS):
            continue
        if glob_filter and not fnmatch(file.name, glob_filter):
            continue
        if _is_binary(file):
            continue
        for line_number, line in enumerate(
            file.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            if regex.search(line):
                results.append(f"{_display(file)}:{line_number}: {line.strip()}")
                if len(results) >= max_results:
                    break
    return results


def main() -> None:
    """Entry point for the installed console script."""
    mcp.run()


if __name__ == "__main__":
    main()
