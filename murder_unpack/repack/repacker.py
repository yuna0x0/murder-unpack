"""Repack modified assets back into Murder Engine .gz format."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from murder_unpack.core.gzip_json import compress_json_gz, load_json


def repack_assets(
    project_dir: Path | str,
    output_dir: Path | str,
    max_per_file: int = 500,
) -> None:
    """Repack individual .json assets back into packed .gz format.

    Reads from the editor project structure and creates:
    - preload_data.gz
    - data0.gz through dataN.gz
    - sounds.gz

    Args:
        project_dir: Path to the recovered project's resources dir
        output_dir: Output directory for .gz files
        max_per_file: Maximum assets per data file (default: 500, matching engine)
    """
    project_dir = Path(project_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Collect all asset .json files
    assets_dir = project_dir / "assets"
    all_assets: list[dict[str, Any]] = []
    preload_assets: list[dict[str, Any]] = []

    if assets_dir.exists():
        for json_file in sorted(assets_dir.rglob("*.json")):
            try:
                asset = load_json(json_file)
            except (json.JSONDecodeError, OSError):
                continue

            # Check if it's a preload asset (in Generated/preload_images or Generated/Libraries)
            rel = json_file.relative_to(assets_dir)
            rel_str = str(rel)
            if "Generated/preload" in rel_str or "Generated/Libraries" in rel_str:
                preload_assets.append(asset)
            else:
                all_assets.append(asset)

    # Split into chunks
    chunks: list[list[dict[str, Any]]] = []
    for i in range(0, len(all_assets), max_per_file):
        chunks.append(all_assets[i:i + max_per_file])

    if not chunks:
        chunks = [[]]

    # Pack preload data
    preload_data = {
        "TotalPackedData": len(chunks),
        "Assets": preload_assets,
    }
    compress_json_gz(preload_data, output_dir / "preload_data.gz")

    # Pack data files
    textures_no_atlas: list[str] = []
    # Try to read from existing game_config or packed data
    for i, chunk in enumerate(chunks):
        packed = {
            "Assets": chunk,
            "TexturesNoAtlasPath": textures_no_atlas if i == 0 else [],
        }
        compress_json_gz(packed, output_dir / f"data{i}.gz")

    # Pack sounds
    sounds_path = project_dir / "sounds.json"
    if sounds_path.exists():
        sound_data = load_json(sounds_path)
    else:
        sound_data = {"Banks": {}, "Plugins": []}
    compress_json_gz(sound_data, output_dir / "sounds.gz")
