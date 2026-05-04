# hermes-claude-memories

Read-only Hermes plugin that discovers Claude Code memory files (`MEMORY.md`, `CLAUDE.md`) and makes them available inside Hermes sessions.

It is a Hermes port of the same idea as `pi-claude-memories`:

- scans Claude Code project auto-memory under `~/.claude/projects/<cwd-encoded>/memory/MEMORY.md`
- falls back through cwd ancestors, so a repo without exact memory can inherit `~/Developer` memory
- scans user auto-memory under `~/.claude/projects/<home-encoded>/memory/MEMORY.md`
- scans `./.claude/CLAUDE.md` and `~/.claude/CLAUDE.md`
- resolves markdown links and Claude `@file.md` imports transitively inside allowed roots
- never writes to Claude files

## Status bar

When the Hermes core status-item API is available, the plugin adds a compact CLI footer item:

```text
🧠 Claude 2
```

Suffixes:

- `🧠 Claude 2…` — memories are queued for injection on the next turn
- `🧠 Claude 2✓` — memories were injected on the last turn

Preferred core API:

```python
ctx.register_status_item(name, callback, priority=100)
```

This repo includes the paired Hermes core patch at `patches/hermes-status-items.patch`.
If a future `hermes update` removes that local core patch, the plugin now installs a
runtime fallback from `~/.hermes/plugins/claude-memories` that monkey-patches the
interactive CLI footer during plugin load. That fallback is stored outside the Hermes
source checkout, so the Claude memory count remains visible after updates even before
the core patch is reapplied.

## Install locally

On a fresh Hermes checkout, apply the core patch for the native status-item API:

```bash
cd ~/.hermes/hermes-agent
git apply ~/.hermes/plugins/claude-memories/patches/hermes-status-items.patch
```

Then install and enable the plugin:

```bash
mkdir -p ~/.hermes/plugins
cp -R ~/Developer/hermes-claude-memories ~/.hermes/plugins/claude-memories
hermes plugins enable claude-memories
```

Restart Hermes after enabling plugins.

## Commands

- `/memories-refresh [cwd]` — rescan Claude memory locations
- `/memories-list` — list cached memory files
- `/memories-show <id>` — show a cached memory file
- `/memories-load` — inject all cached memory files on the next turn

## Trigger phrases

If a user message contains one of these phrases, the plugin injects the full cached memory contents into the turn as a `<claude-memory>` block:

- `read memories`
- `check memories`
- `load memories`
- `remember memories`
- `use memories`
- `@memories`

Otherwise, by default it injects only a small index of available memory files.

## Environment variables

- `HERMES_CLAUDE_MEMORIES_DIR` — override Claude config root, default `~/.claude`
- `HERMES_CLAUDE_MEMORIES_TRIGGERS` — comma-separated trigger phrases
- `HERMES_CLAUDE_MEMORIES_INDEX=false` — disable passive index injection
- `HERMES_CLAUDE_MEMORIES_MAX_BYTES=200000` — cap full injected content size

The plugin also accepts the equivalent `PI_CLAUDE_MEMORIES_*` variables for compatibility.

## Development

```bash
python -m pytest -q
```
