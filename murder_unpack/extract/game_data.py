"""Load and index all packed game data from Murder Engine exports."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator

from murder_unpack.core.gzip_json import decompress_gz_json, load_json


class GameDatabase:
    """Loads and indexes all assets from a Murder Engine game export."""

    def __init__(self) -> None:
        self.assets: list[dict[str, Any]] = []
        self.preload_assets: list[dict[str, Any]] = []
        self.sound_data: dict[str, Any] = {}
        self.game_config: dict[str, Any] = {}
        self.textures_no_atlas: list[str] = []
        self._by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._by_guid: dict[str, dict[str, Any]] = {}
        self._by_name: dict[str, dict[str, Any]] = {}
        self.total_packed_data: int = 0

    def load(self, game_dir: Path | str) -> None:
        """Load all game data from a game directory.

        Args:
            game_dir: Path to game root (containing resources/ directory)
        """
        game_dir = Path(game_dir)
        content_dir = game_dir / "resources" / "content"
        config_path = game_dir / "resources" / "game_config"

        if config_path.exists():
            self.game_config = load_json(config_path)

        # Load preload data first — it tells us how many data files exist
        preload_path = content_dir / "preload_data.gz"
        if preload_path.exists():
            preload = decompress_gz_json(preload_path)
            self.total_packed_data = preload.get("TotalPackedData", 0)
            self.preload_assets = preload.get("Assets", [])
            for asset in self.preload_assets:
                self._index_asset(asset)

        # Load data files
        for i in range(self.total_packed_data):
            data_path = content_dir / f"data{i}.gz"
            if not data_path.exists():
                continue
            packed = decompress_gz_json(data_path)
            assets = packed.get("Assets", [])
            if i == 0:
                self.textures_no_atlas = packed.get("TexturesNoAtlasPath", [])
            for asset in assets:
                self.assets.append(asset)
                self._index_asset(asset)

        # Load sound data
        sounds_path = content_dir / "sounds.gz"
        if sounds_path.exists():
            self.sound_data = decompress_gz_json(sounds_path)

    def _index_asset(self, asset: dict[str, Any]) -> None:
        type_name = asset.get("$type", "")
        self._by_type[type_name].append(asset)
        guid = asset.get("Guid", "")
        if guid:
            self._by_guid[guid] = asset
        name = asset.get("Name", "")
        if name:
            self._by_name[name] = asset

    def get_by_type(self, type_name: str) -> list[dict[str, Any]]:
        return self._by_type.get(type_name, [])

    def get_by_guid(self, guid: str) -> dict[str, Any] | None:
        return self._by_guid.get(guid)

    def get_by_name(self, name: str) -> dict[str, Any] | None:
        return self._by_name.get(name)

    def search(self, query: str) -> list[dict[str, Any]]:
        """Search assets by name (case-insensitive substring match)."""
        q = query.lower()
        return [a for a in self.all_assets() if q in a.get("Name", "").lower()]

    def all_assets(self) -> Iterator[dict[str, Any]]:
        yield from self.preload_assets
        yield from self.assets

    def list_types(self) -> dict[str, int]:
        """Return a dict of type_name → count."""
        return {k: len(v) for k, v in sorted(self._by_type.items())}

    @property
    def total_assets(self) -> int:
        return len(self.preload_assets) + len(self.assets)

    def get_atlas_names(self, game_dir: Path | str) -> list[str]:
        """List available atlas names from atlas directory."""
        atlas_dir = Path(game_dir) / "resources" / "atlas"
        if not atlas_dir.exists():
            return []
        return [p.stem for p in sorted(atlas_dir.glob("*.json"))]

    def load_atlas_metadata(self, game_dir: Path | str, atlas_name: str) -> dict[str, Any]:
        """Load atlas JSON metadata."""
        atlas_path = Path(game_dir) / "resources" / "atlas" / f"{atlas_name}.json"
        return load_json(atlas_path)
