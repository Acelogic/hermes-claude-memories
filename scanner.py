"""Claude Code memory discovery for the Hermes claude-memories plugin."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_TRIGGERS = (
    "read memories",
    "check memories",
    "load memories",
    "remember memories",
    "use memories",
    "@memories",
)
DEFAULT_MAX_BYTES = 200_000
MAX_IMPORT_DEPTH = 5


@dataclass(frozen=True)
class MemorySource:
    id: str
    label: str
    path: str
    content: str
    kind: str
    scope: str


def claude_root() -> Path:
    override = os.environ.get("HERMES_CLAUDE_MEMORIES_DIR") or os.environ.get("PI_CLAUDE_MEMORIES_DIR")
    if override and override.strip():
        return Path(_expand_home(override.strip())).resolve()
    return Path.home() / ".claude"


def max_bytes() -> int:
    raw = os.environ.get("HERMES_CLAUDE_MEMORIES_MAX_BYTES") or os.environ.get("PI_CLAUDE_MEMORIES_MAX_BYTES")
    if not raw:
        return DEFAULT_MAX_BYTES
    try:
        value = int(raw.strip())
        return value if value > 0 else DEFAULT_MAX_BYTES
    except Exception:
        return DEFAULT_MAX_BYTES


def triggers() -> tuple[str, ...]:
    raw = os.environ.get("HERMES_CLAUDE_MEMORIES_TRIGGERS") or os.environ.get("PI_CLAUDE_MEMORIES_TRIGGERS")
    if not raw:
        return DEFAULT_TRIGGERS
    return tuple(s.strip().lower() for s in raw.split(",") if s.strip())


def index_enabled() -> bool:
    raw = os.environ.get("HERMES_CLAUDE_MEMORIES_INDEX")
    if raw is None:
        raw = os.environ.get("PI_CLAUDE_MEMORIES_INDEX")
    if raw is None or not raw.strip():
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def encode_path(path: str | Path) -> str:
    return str(Path(path).resolve()).replace("/", "-")


def _expand_home(path: str) -> str:
    if path == "~":
        return str(Path.home())
    if path.startswith("~/"):
        return str(Path.home() / path[2:])
    return path


def _safe_read(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _is_ancestor_of(root: Path, descendant: Path) -> bool:
    root = root.resolve()
    descendant = descendant.resolve()
    return root == descendant or root in descendant.parents


def _ancestor_dirs(cwd: Path) -> list[Path]:
    cwd = cwd.resolve()
    return [cwd, *cwd.parents]


def _resolve_ref(raw_ref: str, from_file: Path) -> Path | None:
    ref = _expand_home(raw_ref.strip())
    if not ref.lower().endswith(".md"):
        return None
    candidate = Path(ref)
    if not candidate.is_absolute():
        candidate = from_file.parent / candidate
    return candidate.resolve()


def _extract_references(content: str) -> list[str]:
    refs: set[str] = set()
    for match in re.finditer(r"\[[^\]]+\]\(([^)\s]+\.md)\)", content):
        target = match.group(1)
        if target and not re.match(r"^(https?|mailto|data):", target, re.I):
            refs.add(target)
    for match in re.finditer(r"(?:^|[\s(])@((?:~/|\.{0,2}/|/)?[^\s)@]+\.md)(?=[\s)]|[.,;:!?]|$)", content, re.M):
        target = match.group(1)
        if target:
            refs.add(target)
    return sorted(refs)


def _gather_transitively(
    file: Path,
    content: str,
    *,
    depth: int,
    allowed_roots: Iterable[Path],
    visited: set[Path],
    sources: list[MemorySource],
    scope: str,
    id_prefix: str,
) -> None:
    if depth > MAX_IMPORT_DEPTH:
        return
    roots = [r.resolve() for r in allowed_roots]
    for ref in _extract_references(content):
        abs_path = _resolve_ref(ref, file)
        if abs_path is None or abs_path in visited:
            continue
        if not any(_is_ancestor_of(root, abs_path) for root in roots):
            continue
        body = _safe_read(abs_path)
        if body is None:
            continue
        visited.add(abs_path)
        sources.append(
            MemorySource(
                id=f"{id_prefix}/{abs_path.name}",
                label=abs_path.name,
                path=str(abs_path),
                content=body,
                kind="memory-file",
                scope=scope,
            )
        )
        _gather_transitively(
            abs_path,
            body,
            depth=depth + 1,
            allowed_roots=roots,
            visited=visited,
            sources=sources,
            scope=scope,
            id_prefix=id_prefix,
        )


def _find_project_memory_dir(cwd: Path, root: Path) -> Path | None:
    home = Path.home().resolve()
    for directory in _ancestor_dirs(cwd):
        if directory.resolve() == home:
            continue
        candidate = root / "projects" / encode_path(directory) / "memory" / "MEMORY.md"
        if _safe_read(candidate) is not None:
            return candidate.parent
    return None


def scan(cwd: str | Path | None = None) -> list[MemorySource]:
    cwd_path = Path(cwd or os.getcwd()).resolve()
    root = claude_root()
    found: list[MemorySource] = []
    visited: set[Path] = set()

    project_memory_dir = _find_project_memory_dir(cwd_path, root)
    if project_memory_dir:
        index_path = project_memory_dir / "MEMORY.md"
        index_content = _safe_read(index_path)
        if index_content is not None:
            visited.add(index_path.resolve())
            found.append(
                MemorySource(
                    id="project/MEMORY.md",
                    label="project memory index",
                    path=str(index_path),
                    content=index_content,
                    kind="memory-index",
                    scope="project",
                )
            )
            _gather_transitively(
                index_path,
                index_content,
                depth=1,
                allowed_roots=[project_memory_dir, root],
                visited=visited,
                sources=found,
                scope="project",
                id_prefix="project",
            )

    user_memory_dir = root / "projects" / encode_path(Path.home()) / "memory"
    user_index_path = user_memory_dir / "MEMORY.md"
    if user_index_path.resolve() not in visited:
        user_content = _safe_read(user_index_path)
        if user_content is not None:
            visited.add(user_index_path.resolve())
            found.append(
                MemorySource(
                    id="user/MEMORY.md",
                    label="user memory index",
                    path=str(user_index_path),
                    content=user_content,
                    kind="memory-index",
                    scope="user",
                )
            )
            _gather_transitively(
                user_index_path,
                user_content,
                depth=1,
                allowed_roots=[user_memory_dir, root],
                visited=visited,
                sources=found,
                scope="user",
                id_prefix="user",
            )

    candidates: list[tuple[Path, str, str]] = [
        (cwd_path / ".claude" / "CLAUDE.md", "./.claude/CLAUDE.md", "project"),
    ]
    if not _is_ancestor_of(root, cwd_path):
        candidates.append((root / "CLAUDE.md", "~/.claude/CLAUDE.md", "user"))

    for path, label, scope in candidates:
        resolved = path.resolve()
        if resolved in visited:
            continue
        content = _safe_read(resolved)
        if content is None:
            continue
        visited.add(resolved)
        found.append(
            MemorySource(
                id=label,
                label=label,
                path=str(resolved),
                content=content,
                kind="claude-md",
                scope=scope,
            )
        )
    return found


def build_index_block(sources: list[MemorySource]) -> str:
    if not sources:
        return ""
    lines = "\n".join(f"- {source.id} — {source.path}" for source in sources)
    return (
        "## Claude Memories (read-only, available via read_file/search_files tools)\n\n"
        "The following Claude Code memory and instruction files exist. "
        "Open them when relevant, or ask to load memories to inline their contents.\n\n"
        f"{lines}"
    )


def build_injection_block(sources: list[MemorySource]) -> str:
    if not sources:
        return "<claude-memory>(no Claude memory files found)</claude-memory>"
    budget = max_bytes()
    parts: list[str] = []
    used = 0
    for source in sources:
        header = f"--- {source.id} ({source.path}) ---\n"
        remaining = budget - used - len(header)
        if remaining <= 200:
            parts.append(header + "[truncated: size budget exhausted]")
            break
        body = source.content
        if len(body) > remaining:
            body = body[:remaining] + "\n[truncated]"
        parts.append(header + body)
        used += len(header) + len(body)
    return "<claude-memory>\n" + "\n\n".join(parts) + "\n</claude-memory>"


def match_trigger(text: str) -> tuple[bool, str]:
    lower = text.lower()
    for phrase in triggers():
        idx = lower.find(phrase)
        if idx != -1:
            stripped = (text[:idx] + text[idx + len(phrase):]).strip()
            return True, stripped
    return False, text
