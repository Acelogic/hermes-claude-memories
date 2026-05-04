import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_plugin():
    name = "claude_memories_plugin_under_test"
    for module_name in [name, f"{name}.scanner"]:
        sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(
        name,
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_fallback_status_patch_appends_claude_memory_count(monkeypatch):
    plugin = load_plugin()
    plugin._cached = [object(), object()]

    class FakeHermesCLI:
        def _get_status_bar_fragments(self):
            return [("class:status-bar", " ⚕ test-model ")]

        def _get_tui_terminal_width(self):
            return 160

        def _get_status_bar_snapshot(self):
            return {"model_short": "test-model"}

        @staticmethod
        def _status_bar_display_width(text):
            return len(text or "")

        @staticmethod
        def _trim_status_bar_text(text, width):
            return text[:width]

    fake_cli = types.ModuleType("cli")
    fake_cli.HermesCLI = FakeHermesCLI
    monkeypatch.setitem(sys.modules, "cli", fake_cli)

    assert plugin._install_status_bar_fallback() is True

    frags = FakeHermesCLI()._get_status_bar_fragments()
    assert "🧠 Claude 2" in "".join(text for _, text in frags)


def test_register_uses_runtime_fallback_without_core_status_api(monkeypatch, tmp_path):
    plugin = load_plugin()

    class FakeHermesCLI:
        def _get_status_bar_fragments(self):
            return [("class:status-bar", " ⚕ test-model ")]

        def _get_tui_terminal_width(self):
            return 160

        def _get_status_bar_snapshot(self):
            return {"model_short": "test-model"}

        @staticmethod
        def _status_bar_display_width(text):
            return len(text or "")

        @staticmethod
        def _trim_status_bar_text(text, width):
            return text[:width]

    fake_cli = types.ModuleType("cli")
    fake_cli.HermesCLI = FakeHermesCLI
    monkeypatch.setitem(sys.modules, "cli", fake_cli)

    home = tmp_path / "home" / "mcruz"
    cwd = home / "Developer" / "repo"
    claude = home / ".claude"
    user_memory = claude / "projects" / str(home.resolve()).replace("/", "-") / "memory"
    cwd.mkdir(parents=True)
    user_memory.mkdir(parents=True)
    (user_memory / "MEMORY.md").write_text("User memory", encoding="utf-8")
    monkeypatch.setattr(plugin.Path, "home", lambda: home)
    monkeypatch.setenv("HERMES_CLAUDE_MEMORIES_DIR", str(claude))

    class CtxWithoutStatusApi:
        workdir = str(cwd)

        def register_hook(self, *_args, **_kwargs):
            pass

        def register_command(self, *_args, **_kwargs):
            pass

    plugin.register(CtxWithoutStatusApi())

    frags = FakeHermesCLI()._get_status_bar_fragments()
    assert "🧠 Claude 1" in "".join(text for _, text in frags)
