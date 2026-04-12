"""Split packed game data into individual asset JSON files for the editor."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from murder_unpack.core.asset_types import get_asset_directory, get_asset_filename
from murder_unpack.core.gzip_json import save_json
from murder_unpack.extract.game_data import GameDatabase


def split_assets(
    db: GameDatabase,
    output_dir: Path | str,
) -> dict[str, int]:
    """Split all packed assets into individual .json files.

    Places each asset in the correct editor directory based on its type.

    Args:
        db: Loaded GameDatabase
        output_dir: Base output directory (the 'resources' dir of the editor project)

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
        save_json(asset, full_dir / filename)

        dir_key = asset_dir or "(root)"
        counts[dir_key] = counts.get(dir_key, 0) + 1

    return counts
