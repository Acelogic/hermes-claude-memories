import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location("hermes_claude_memories.scanner", ROOT / "scanner.py")
scanner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = scanner
spec.loader.exec_module(scanner)


def test_scan_finds_project_ancestor_and_user_memory(tmp_path, monkeypatch):
    home = tmp_path / "home" / "mcruz"
    cwd = home / "Developer" / "repo"
    claude = home / ".claude"
    cwd.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HERMES_CLAUDE_MEMORIES_DIR", str(claude))

    project_dir = claude / "projects" / scanner.encode_path(home / "Developer") / "memory"
    project_dir.mkdir(parents=True)
    (project_dir / "MEMORY.md").write_text("Project index @details.md", encoding="utf-8")
    (project_dir / "details.md").write_text("Project details", encoding="utf-8")

    user_dir = claude / "projects" / scanner.encode_path(home) / "memory"
    user_dir.mkdir(parents=True)
    (user_dir / "MEMORY.md").write_text("User index", encoding="utf-8")

    sources = scanner.scan(cwd)

    assert [source.id for source in sources] == [
        "project/MEMORY.md",
        "project/details.md",
        "user/MEMORY.md",
    ]


def test_trigger_strips_phrase():
    matched, stripped = scanner.match_trigger("please use memories and answer")

    assert matched is True
    assert stripped == "please  and answer"


def test_injection_block_respects_budget(monkeypatch):
    monkeypatch.setenv("HERMES_CLAUDE_MEMORIES_MAX_BYTES", "260")
    source = scanner.MemorySource(
        id="project/MEMORY.md",
        label="project",
        path="/tmp/MEMORY.md",
        content="x" * 1000,
        kind="memory-index",
        scope="project",
    )

    block = scanner.build_injection_block([source])

    assert block.startswith("<claude-memory>")
    assert "[truncated]" in block
