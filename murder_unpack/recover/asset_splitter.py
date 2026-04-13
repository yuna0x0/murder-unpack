"""Split packed game data into individual asset JSON files for the editor."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from murder_unpack.core.asset_types import get_asset_directory, get_asset_filename
from murder_unpack.core.gzip_json import save_json
from murder_unpack.extract.game_data import GameDatabase


def detect_game_assembly(db: GameDatabase) -> str | None:
    """Detect the original game assembly name from packed data.

    Scans for assembly-qualified type names like:
        Road.Components.Foo, Neverway, Version=1.0.0.0, ...
    and returns the non-engine assembly name (e.g., "Neverway").
    """
    skip = {"Murder", "Bang", "System", "Microsoft", "MonoGame", "FNA", "Gum"}

    def scan(obj: Any, depth: int = 0) -> str | None:
        if depth > 8:
            return None
        if isinstance(obj, str):
            m = re.search(r", ([A-Za-z][A-Za-z0-9_.]+), Version=", obj)
            if m and m.group(1) not in skip:
                return m.group(1)
        elif isinstance(obj, dict):
            for k in obj:
                if isinstance(k, str):
                    result = scan(k, depth + 1)
                    if result:
                        return result
            for v in obj.values():
                result = scan(v, depth + 1)
                if result:
                    return result
        elif isinstance(obj, list):
            for v in obj:
                result = scan(v, depth + 1)
                if result:
                    return result
        return None

    for asset in db.all_assets():
        result = scan(asset)
        if result:
            return result
    return None


def remap_assembly_names(obj: Any, old_name: str, new_name: str) -> Any:
    """Recursively remap assembly names in JSON data.

    Replaces ', OldAssembly, Version=' with ', NewAssembly, Version='
    in both dict keys and string values.
    """
    old_pattern = f", {old_name}, "
    new_pattern = f", {new_name}, "

    if isinstance(obj, str):
        if old_pattern in obj:
            return obj.replace(old_pattern, new_pattern)
        return obj
    elif isinstance(obj, dict):
        new_dict = {}
        for k, v in obj.items():
            new_k = k.replace(old_pattern, new_pattern) if isinstance(k, str) and old_pattern in k else k
            new_dict[new_k] = remap_assembly_names(v, old_name, new_name)
        return new_dict
    elif isinstance(obj, list):
        return [remap_assembly_names(v, old_name, new_name) for v in obj]
    return obj


def split_assets(
    db: GameDatabase,
    output_dir: Path | str,
    assembly_remap: tuple[str, str] | None = None,
) -> dict[str, int]:
    """Split all packed assets into individual .json files.

    Places each asset in the correct editor directory based on its type.

    Args:
        db: Loaded GameDatabase
        output_dir: Base output directory (the 'resources' dir of the editor project)
        assembly_remap: Optional (old_name, new_name) to remap assembly names

    Returns:
        Dict of directory → count of assets written
    """
    output_dir = Path(output_dir)
    counts: dict[str, int] = {}
    seen_paths: set[str] = set()

    for asset in db.all_assets():
        asset_dir = get_asset_directory(asset)

        # GameProfile goes to root as game_config
        type_name = asset.get("$type", "")
        if type_name in ("Murder.Assets.GameProfile", "Road.Assets.RoadGameProfile"):
            continue  # Handled separately

        # Remap assembly names if needed
        write_asset = asset
        if assembly_remap:
            write_asset = remap_assembly_names(asset, *assembly_remap)

        filename = get_asset_filename(asset)

        # Handle name collisions
        if asset_dir:
            full_dir = output_dir / asset_dir
        else:
            full_dir = output_dir

        full_path = str(full_dir / filename)
        if full_path in seen_paths:
            guid = asset.get("Guid", "")
            base, ext = filename.rsplit(".", 1)
            filename = f"{base}_{guid[:8]}.{ext}"
            full_path = str(full_dir / filename)

        seen_paths.add(full_path)
        full_dir.mkdir(parents=True, exist_ok=True)

        # Write the bare asset JSON (not wrapped in PackedGameData)
        save_json(write_asset, full_dir / filename)

        dir_key = asset_dir or "(root)"
        counts[dir_key] = counts.get(dir_key, 0) + 1

    return counts
