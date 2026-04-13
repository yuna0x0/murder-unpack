"""Per-game decompiler fix registry.

Decompiled code sometimes has game-specific issues that can't be fixed
generically (e.g., lost tuple element names, readonly field assignments,
duplicate local functions). This module provides a registry of known
per-game fixes that are auto-detected and applied during recovery.

Detection uses multiple signals: assembly name, game namespace, Steam App ID,
game_config fingerprinting. CLI override via --game-fix <id>.

Adding a new game fix:
1. Create a module in murder_unpack/fixes/ (e.g., my_game.py)
2. Define a GameFix instance with detection criteria and fix actions
3. Register it by adding to _BUILTIN_FIXES in this file

Or via plugin system: call registry.register(fix) from your plugin's
register() function.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from murder_unpack.extract.game_data import GameDatabase


@dataclass
class Replacement:
    """A text replacement in a specific file."""
    file_glob: str  # glob pattern relative to decompiled dir
    old: str
    new: str
    description: str = ""


@dataclass
class GameFix:
    """A collection of fixes for a specific game."""
    id: str  # unique identifier (e.g., "neverway")
    name: str  # display name (e.g., "Neverway Prologue")

    # Detection criteria — any match triggers this fix
    assembly_names: list[str] = field(default_factory=list)
    game_namespaces: list[str] = field(default_factory=list)
    steam_app_ids: list[str] = field(default_factory=list)
    game_config_types: list[str] = field(default_factory=list)

    # Fix actions
    replacements: list[Replacement] = field(default_factory=list)
    # For complex fixes that can't be expressed as simple replacements
    custom_fix: Callable[[Path], int] | None = None

    def matches(
        self,
        db: GameDatabase | None = None,
        game_dir: Path | None = None,
        assembly_name: str | None = None,
    ) -> bool:
        """Check if this fix matches the given game."""
        if assembly_name and assembly_name in self.assembly_names:
            return True
        if db:
            ns = db.game_namespace
            if ns and ns in self.game_namespaces:
                return True
            config_type = db.game_config.get("$type", "")
            if config_type and config_type in self.game_config_types:
                return True
        if game_dir:
            # Check steam_appid.txt
            for appid_file in ("steam_appid.txt",):
                p = game_dir / appid_file
                if p.exists():
                    appid = p.read_text().strip()
                    if appid in self.steam_app_ids:
                        return True
        return False

    def apply(self, decompiled_dir: Path) -> int:
        """Apply all fixes. Returns count of files modified."""
        count = 0

        for r in self.replacements:
            for cs_file in decompiled_dir.rglob(r.file_glob):
                try:
                    src = cs_file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                if r.old in src:
                    new_src = src.replace(r.old, r.new)
                    if new_src != src:
                        cs_file.write_text(new_src, encoding="utf-8")
                        count += 1

        if self.custom_fix:
            count += self.custom_fix(decompiled_dir)

        return count


class FixRegistry:
    """Registry of known per-game fixes."""

    def __init__(self) -> None:
        self._fixes: dict[str, GameFix] = {}

    def register(self, fix: GameFix) -> None:
        self._fixes[fix.id] = fix

    def get(self, fix_id: str) -> GameFix | None:
        return self._fixes.get(fix_id)

    def detect(
        self,
        db: GameDatabase | None = None,
        game_dir: Path | None = None,
        assembly_name: str | None = None,
    ) -> GameFix | None:
        """Auto-detect which game fix to apply."""
        for fix in self._fixes.values():
            if fix.matches(db=db, game_dir=game_dir, assembly_name=assembly_name):
                return fix
        return None

    def list_all(self) -> list[GameFix]:
        return list(self._fixes.values())


# Global registry
_registry = FixRegistry()


def get_registry() -> FixRegistry:
    """Get the global fix registry, loading built-in fixes on first call."""
    if not _registry._fixes:
        _load_builtin_fixes()
    return _registry


def _load_builtin_fixes() -> None:
    """Load all built-in game fixes."""
    from murder_unpack.fixes import neverway
    _registry.register(neverway.FIX)
