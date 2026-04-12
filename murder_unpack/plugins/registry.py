"""Plugin discovery and registration.

Two discovery paths:
1. Drop-in .py files from ~/.murder-unpack/plugins/ and ./plugins/
2. pip-installed packages via importlib.metadata entry_points

Both feed into a single PluginRegistry.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import sys
from pathlib import Path
from typing import Any

import click

ENTRY_POINT_GROUPS = {
    "asset_handlers": "murder_unpack.asset_handlers",
    "extractors": "murder_unpack.extractors",
    "commands": "murder_unpack.commands",
    "hooks": "murder_unpack.hooks",
}

def _default_plugin_dirs() -> list[Path]:
    return [
        Path.home() / ".murder-unpack" / "plugins",
        Path.cwd() / "plugins",
    ]


class PluginRegistry:
    """Central registry for all loaded plugins."""

    def __init__(self) -> None:
        self.asset_handlers: dict[str, Any] = {}
        self.extractors: dict[str, Any] = {}
        self.commands: dict[str, Any] = {}
        self.hooks: dict[str, list[Any]] = {
            "pre_extract": [],
            "post_extract": [],
            "pre_recover": [],
            "post_recover": [],
        }
        self._loaded_files: set[str] = set()

    def discover_all(self, plugin_dirs: list[Path] | None = None) -> None:
        """Load plugins from both drop-in directories and entry points."""
        dirs = plugin_dirs or _default_plugin_dirs()

        # 1. Directory-based (drop-in .py files)
        for d in dirs:
            if d.is_dir():
                for f in sorted(d.glob("*.py")):
                    if f.name.startswith("_"):
                        continue
                    self._load_file(f)

        # 2. Entry-point-based (pip-installed packages)
        for category, group in ENTRY_POINT_GROUPS.items():
            for ep in importlib.metadata.entry_points(group=group):
                try:
                    obj = ep.load()
                    self._register(category, ep.name, obj)
                except Exception as e:
                    click.echo(f"Warning: failed to load plugin {ep.name}: {e}", err=True)

    def _load_file(self, path: Path) -> None:
        """Load a single .py plugin file."""
        key = str(path.resolve())
        if key in self._loaded_files:
            return
        self._loaded_files.add(key)

        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            return

        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as e:
            click.echo(f"Warning: failed to load plugin {path.name}: {e}", err=True)
            return

        # Convention: module defines register(registry) function
        if hasattr(mod, "register"):
            try:
                mod.register(self)
            except Exception as e:
                click.echo(f"Warning: register() failed for {path.name}: {e}", err=True)

    def _register(self, category: str, name: str, obj: Any) -> None:
        if category == "hooks":
            stage = getattr(obj, "stage", "post_extract")
            if stage in self.hooks:
                self.hooks[stage].append(obj)
        elif hasattr(self, category):
            target = getattr(self, category)
            if isinstance(target, dict):
                target[name] = obj

    def run_hooks(self, stage: str, context: dict[str, Any]) -> dict[str, Any]:
        """Execute all hooks for a given stage."""
        for hook in self.hooks.get(stage, []):
            try:
                context = hook.run(context)
            except Exception as e:
                click.echo(f"Warning: hook failed at {stage}: {e}", err=True)
        return context

    def list_plugins(self) -> dict[str, list[str]]:
        """List all loaded plugins by category."""
        result: dict[str, list[str]] = {}
        if self.asset_handlers:
            result["asset_handlers"] = list(self.asset_handlers.keys())
        if self.extractors:
            result["extractors"] = list(self.extractors.keys())
        if self.commands:
            result["commands"] = list(self.commands.keys())
        hook_count = sum(len(v) for v in self.hooks.values())
        if hook_count:
            result["hooks"] = [
                f"{stage}: {len(hooks)}" for stage, hooks in self.hooks.items() if hooks
            ]
        return result

    def plugin_dirs(self) -> list[Path]:
        """Return the plugin directories being searched."""
        return _default_plugin_dirs()
