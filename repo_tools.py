"""Read-only repository tools for the Claude Fable 5.1 developer agent.

The model never touches the filesystem. It asks for a path, and this module
decides whether that path is allowed. Every request is resolved against a single
allowed root, so a path the model invents cannot escape the project.
"""

from __future__ import annotations

import json
from pathlib import Path

MAX_FILE_BYTES = 40_000
MAX_LISTED_FILES = 200

# Extensions worth reading in a code review. Anything else is skipped rather
# than handed to the model as bytes it cannot use.
TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".toml", ".cfg", ".ini", ".json", ".yaml", ".yml",
    ".html", ".css", ".js", ".ts", ".sql", ".sh",
}

# Directories that never help and often hurt.
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache", ".idea", ".vscode"}

# Files that must stay unreadable even though they sit inside the project.
DENY_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "credentials.json"}


class ToolError(Exception):
    """Raised when a tool call is refused. Sent back as a tool error result."""


class ProjectReader:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError(f"{self.root} is not a directory")

    # ---------------------------------------------------------------- guards

    def _resolve(self, relative_path: str) -> Path:
        if not relative_path or not relative_path.strip():
            raise ToolError("path must not be empty")

        relative = Path(relative_path)
        if relative.is_absolute() or relative.drive:
            raise ToolError(f"path is outside the project root: {relative_path}")

        # Check each unresolved path component before resolve() follows it.
        cursor = self.root
        for part in relative.parts:
            cursor /= part
            if cursor.is_symlink():
                raise ToolError(f"symlinks are not followed: {relative_path}")

        candidate = (self.root / relative).resolve()

        # After resolving "..", the path still has to sit under the root.
        if candidate != self.root and self.root not in candidate.parents:
            raise ToolError(f"path is outside the project root: {relative_path}")

        if candidate.name in DENY_NAMES:
            raise ToolError(f"reading {candidate.name} is not allowed")

        if any(part in SKIP_DIRS for part in candidate.parts):
            raise ToolError(f"path is in an excluded directory: {relative_path}")

        return candidate

    # ----------------------------------------------------------------- tools

    def list_project_files(self) -> str:
        files = []
        for path in sorted(self.root.rglob("*")):
            if path.is_dir() or path.is_symlink():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.name in DENY_NAMES:
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            files.append(f"{path.relative_to(self.root).as_posix()} ({path.stat().st_size} bytes)")
            if len(files) >= MAX_LISTED_FILES:
                files.append(f"... truncated at {MAX_LISTED_FILES} files")
                break
        return "\n".join(files) if files else "no readable files found"

    def read_project_file(self, path: str) -> str:
        target = self._resolve(path)

        if not target.exists():
            raise ToolError(f"file not found: {path}")
        if target.is_dir():
            raise ToolError(f"{path} is a directory, not a file")
        if target.suffix.lower() not in TEXT_SUFFIXES:
            raise ToolError(f"{path} is not a readable text file")

        size = target.stat().st_size
        text = target.read_text(encoding="utf-8", errors="replace")
        if size > MAX_FILE_BYTES:
            text = text[:MAX_FILE_BYTES] + f"\n... truncated, file is {size} bytes"
        return text

    def get_project_metadata(self) -> str:
        counts: dict[str, int] = {}
        total = 0
        for path in self.root.rglob("*"):
            if path.is_dir() or path.is_symlink():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            suffix = path.suffix.lower() or "(none)"
            counts[suffix] = counts.get(suffix, 0) + 1
            total += 1

        manifests = {}
        for name in ("requirements.txt", "pyproject.toml", "package.json", "Pipfile"):
            candidate = self.root / name
            if candidate.is_file():
                manifests[name] = candidate.read_text(encoding="utf-8", errors="replace")[:2000]

        return json.dumps(
            {
                "project_name": self.root.name,
                "total_files": total,
                "files_by_extension": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
                "top_level_entries": sorted(
                    p.name for p in self.root.iterdir() if p.name not in SKIP_DIRS
                ),
                "manifests": manifests,
            },
            indent=2,
        )

    # --------------------------------------------------------------- dispatch

    def run(self, name: str, tool_input: dict) -> tuple[str, bool]:
        """Return (result_text, is_error) so the caller can set is_error on the
        tool_result block."""
        try:
            if name == "list_project_files":
                return self.list_project_files(), False
            if name == "read_project_file":
                return self.read_project_file(tool_input.get("path", "")), False
            if name == "get_project_metadata":
                return self.get_project_metadata(), False
            raise ToolError(f"unknown tool: {name}")
        except ToolError as exc:
            return str(exc), True
        except OSError as exc:
            return f"could not read path: {exc}", True


# Tool schemas sent to the API. strict is on so the arguments the model sends
# are validated against the schema before they reach Python.
TOOLS = [
    {
        "name": "list_project_files",
        "description": (
            "List the readable text files in the project with their sizes. "
            "Call this first to learn the layout before reading anything."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "read_project_file",
        "description": (
            "Read one text file from the project. Paths are relative to the project "
            "root. Request several independent files in the same turn when you can."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path relative to the project root, for example routes/public.py",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "get_project_metadata",
        "description": (
            "Return the project name, file counts by extension, top level entries, "
            "and the contents of any dependency manifest."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
]
