"""Hermes plugin that exposes Claude Code memories to Hermes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    from .scanner import (
        MemorySource,
        build_index_block,
        build_injection_block,
        index_enabled,
        match_trigger,
        scan,
    )
except ImportError:  # Allows pytest to import this plugin directory directly.
    from scanner import (  # type: ignore
        MemorySource,
        build_index_block,
        build_injection_block,
        index_enabled,
        match_trigger,
        scan,
    )

_cached: list[MemorySource] = []
_force_inject_next = False
_loaded_last_turn = False
_last_cwd = ""
_fallback_status_patch_installed = False


def _current_cwd(ctx: Any = None) -> str:
    if ctx is not None:
        for attr in ("cwd", "project_dir", "workdir"):
            value = getattr(ctx, attr, None)
            if value:
                return str(value)
    return os.environ.get("TERMINAL_CWD") or os.getcwd()


def _refresh(cwd: str | None = None) -> list[MemorySource]:
    global _cached, _last_cwd
    _last_cwd = str(Path(cwd or _current_cwd()).resolve())
    _cached = scan(_last_cwd)
    return _cached


def _format_source(source: MemorySource) -> str:
    prefix = "[proj]" if source.scope == "project" else "[user]"
    return f"{prefix} {source.id} — {source.path}"


def _status_fragments(**_kwargs):
    count = len(_cached)
    if count <= 0:
        return []
    suffix = "✓" if _loaded_last_turn else "…" if _force_inject_next else ""
    return [("class:status-bar-dim", f"🧠 Claude {count}{suffix}")]


def _coerce_status_fragments(rendered):
    if not rendered:
        return []
    if isinstance(rendered, str):
        return [("class:status-bar-dim", rendered)]
    try:
        return list(rendered)
    except TypeError:
        return []


def _install_status_bar_fallback() -> bool:
    """Patch the CLI footer at runtime when Hermes lacks status-item API.

    The preferred path is Hermes core's ``ctx.register_status_item`` API.  A
    ``hermes update`` can remove that local core patch, though; this fallback
    lives in the user plugin directory and is loaded before ``cli.HermesCLI`` is
    instantiated, so the Claude memory count survives updates even when the
    core API disappears.
    """
    global _fallback_status_patch_installed
    if _fallback_status_patch_installed:
        return True
    try:
        import cli as hermes_cli_module

        HermesCLI = getattr(hermes_cli_module, "HermesCLI")
        original = getattr(HermesCLI, "_get_status_bar_fragments")
        if getattr(original, "_claude_memories_fallback", False):
            _fallback_status_patch_installed = True
            return True

        def patched_get_status_bar_fragments(self, *args, **kwargs):
            frags = original(self, *args, **kwargs)
            try:
                if not frags:
                    return frags
                existing_text = "".join(text for _, text in frags)
                if "🧠 Claude" in existing_text:
                    return frags

                width = self._get_tui_terminal_width()
                snapshot = self._get_status_bar_snapshot()
                plugin_frags = _coerce_status_fragments(
                    _status_fragments(cli=self, snapshot=snapshot, width=width)
                )
                if not plugin_frags:
                    return frags

                out = list(frags)
                out.append(("class:status-bar-dim", " │ "))
                out.extend(plugin_frags)
                total_width = sum(self._status_bar_display_width(text) for _, text in out)
                if total_width > width:
                    plain_text = "".join(text for _, text in out)
                    trimmed = self._trim_status_bar_text(plain_text, width)
                    return [("class:status-bar", trimmed)]
                return out
            except Exception:
                return frags

        patched_get_status_bar_fragments._claude_memories_fallback = True
        patched_get_status_bar_fragments._claude_memories_original = original
        HermesCLI._get_status_bar_fragments = patched_get_status_bar_fragments
        _fallback_status_patch_installed = True
        return True
    except Exception:
        return False


def _pre_llm_call(**kwargs):
    global _force_inject_next, _loaded_last_turn
    user_message = kwargs.get("user_message") or ""
    cwd = kwargs.get("cwd") or kwargs.get("workdir") or _last_cwd or _current_cwd()
    if not _cached or str(Path(cwd).resolve()) != _last_cwd:
        _refresh(cwd)

    if not _cached:
        _loaded_last_turn = False
        return None

    matched, stripped = match_trigger(user_message)
    should_inject = matched or _force_inject_next
    if should_inject:
        _force_inject_next = False
        _loaded_last_turn = True
        tail = stripped.strip() if matched else user_message.strip()
        if not tail:
            tail = "Please acknowledge the loaded Claude memories."
        return {"context": build_injection_block(_cached), "user_message": tail}

    _loaded_last_turn = False
    if index_enabled():
        return {"context": build_index_block(_cached)}
    return None


def register(ctx):
    """Register Claude memory hooks, slash commands, and status item."""
    _refresh(_current_cwd(ctx))

    def memories_refresh(args: str = "") -> str:
        cwd = args.strip() or _current_cwd(ctx)
        sources = _refresh(cwd)
        return f"Claude memories: {len(sources)} file(s) cached for {Path(cwd).resolve()}"

    def memories_list(_args: str = "") -> str:
        if not _cached:
            return "No Claude memory files cached. Run /memories-refresh."
        return "Cached Claude memories:\n" + "\n".join(_format_source(source) for source in _cached)

    def memories_show(args: str = "") -> str:
        ident = args.strip()
        if not ident:
            return memories_list()
        for source in _cached:
            if source.id == ident or source.label == ident or Path(source.path).name == ident:
                return f"{source.path}\n\n{source.content}"
        return f"Not cached: {ident}"

    def memories_load(_args: str = "") -> str:
        global _force_inject_next
        if not _cached:
            return "No Claude memory files cached. Run /memories-refresh."
        _force_inject_next = True
        return f"Will inject {len(_cached)} Claude memory file(s) on the next turn."

    ctx.register_hook("pre_llm_call", _pre_llm_call)
    if hasattr(ctx, "register_status_item"):
        ctx.register_status_item("claude-memories", _status_fragments, priority=80)
    else:
        _install_status_bar_fallback()

    ctx.register_command("memories-refresh", memories_refresh, "Rescan Claude Code memory locations", args_hint="[cwd]")
    ctx.register_command("memories-list", memories_list, "List cached Claude Code memory files")
    ctx.register_command("memories-show", memories_show, "Show one cached Claude Code memory file", args_hint="<id>")
    ctx.register_command("memories-load", memories_load, "Inject all cached Claude memories on the next turn")
