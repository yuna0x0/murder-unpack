"""Load and index all packed game data from Murder Engine exports."""

from __future__ import annotations

import json
import warnings
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

        Supports two Murder Engine data layouts:
        - Packed (published builds): resources/content/ with data0.gz..dataN.gz
        - Source (editor/dev builds): resources/assets/data/ and assets/ecs/
                                      with individual .json files

        Both use resources/game_config (some games ship game_config.json).

        Args:
            game_dir: Path to game root (containing resources/ directory)
        """
        game_dir = Path(game_dir)

        assets_dir = game_dir / "resources" / "assets"
        content_dir = game_dir / "resources" / "content"

        # Load game_config (some games add .json extension)
        for config_name in ("game_config.json", "game_config"):
            config_path = game_dir / "resources" / config_name
            if config_path.exists():
                self.game_config = load_json(config_path)
                break

        if assets_dir.is_dir():
            self._load_source_assets(assets_dir)
        if content_dir.is_dir():
            self._load_packed_content(content_dir)

    def _load_source_assets(self, assets_dir: Path) -> None:
        """Load individual .json asset files (source/editor layout)."""
        for json_file in sorted(assets_dir.rglob("*.json")):
            try:
                asset = load_json(json_file)
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(asset, dict) and "$type" in asset:
                self.assets.append(asset)
                self._index_asset(asset)

    def _load_packed_content(self, content_dir: Path) -> None:
        """Load packed .gz data files (published build layout)."""
        # Load preload data first — it tells us how many data files exist
        preload_path = content_dir / "preload_data.gz"
        if preload_path.exists():
            preload = decompress_gz_json(preload_path)
            self.total_packed_data = preload.get("TotalPackedData", 0)
            self.preload_assets = preload.get("Assets", [])
            for asset in self.preload_assets:
                self._index_asset(asset)

        # Load data files
        missing = []
        for i in range(self.total_packed_data):
            data_path = content_dir / f"data{i}.gz"
            if not data_path.exists():
                missing.append(f"data{i}.gz")
                continue
            packed = decompress_gz_json(data_path)
            assets = packed.get("Assets", [])
            if i == 0:
                self.textures_no_atlas = packed.get("TexturesNoAtlasPath", [])
            for asset in assets:
                self.assets.append(asset)
                self._index_asset(asset)

        if missing:
            warnings.warn(
                f"Missing {len(missing)}/{self.total_packed_data} data files: "
                f"{', '.join(missing)}. Recovery may be incomplete.",
                stacklevel=2,
            )

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

    @property
    def game_namespace(self) -> str | None:
        """Auto-detect the game's root namespace from asset $type fields.

        Scans all type names, filters out Murder/Bang/System engine types,
        and returns the most common root namespace (e.g., "MyGame").
        """
        if hasattr(self, "_game_namespace"):
            return self._game_namespace

        engine_roots = {
            "Murder", "Bang", "Gum", "System", "Microsoft",
            "MonoGame", "FNA", "Newtonsoft",
        }
        counts: dict[str, int] = {}
        for type_name in self._by_type:
            root = type_name.split(".")[0] if "." in type_name else ""
            if root and root not in engine_roots:
                counts[root] = counts.get(root, 0) + len(self._by_type[type_name])

        self._game_namespace = max(counts, key=counts.get) if counts else None
        return self._game_namespace

    def find_types(self, suffix: str) -> list[str]:
        """Find all type names ending with the given suffix.

        Example: db.find_types("SpeakerAsset") might return
        ["MyGame.Assets.MySpeakerAsset", "Murder.Assets.Dialogs.SpeakerAsset"]
        """
        return [t for t in self._by_type if t.endswith(suffix)]

    def get_by_type_suffix(self, suffix: str) -> list[dict[str, Any]]:
        """Get all assets whose $type ends with the given suffix."""
        results: list[dict[str, Any]] = []
        for type_name, assets in self._by_type.items():
            if type_name.endswith(suffix):
                results.extend(assets)
        return results

    def is_game_type(self, type_name: str) -> bool:
        """Check if a type belongs to the game (not the engine)."""
        ns = self.game_namespace
        return ns is not None and type_name.startswith(f"{ns}.")
