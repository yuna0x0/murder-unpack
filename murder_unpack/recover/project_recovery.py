"""Full editor project recovery orchestrator.

Reverses the Murder Engine export process: unpacks .gz data files,
splits assets into individual .json files, creates a C# project scaffold,
and optionally clones the engine at a specific version.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import click

from murder_unpack.core.gzip_json import load_json, save_json
from murder_unpack.extract.game_data import GameDatabase
from murder_unpack.recover.asset_splitter import split_assets
from murder_unpack.recover.engine_manager import clone_engine
from murder_unpack.recover.scaffold import generate_editor_config, generate_solution
from murder_unpack.recover.stub_generator import generate_stubs


def recover_project(
    game_dir: Path | str,
    output_dir: Path | str,
    game_name: str | None = None,
    engine_version: str = "main",
    engine_path: Path | str | None = None,
    skip_engine: bool = False,
    generate_stubs_flag: bool = True,
) -> None:
    """Recover a Murder Engine game export into an editor-openable project.

    Args:
        game_dir: Path to exported game (containing resources/)
        output_dir: Output directory for recovered project
        game_name: Project name (auto-detected from game_config if None)
        engine_version: Murder engine version (branch/tag/commit)
        engine_path: Path to existing engine clone (instead of cloning)
        skip_engine: Don't clone/copy engine
        generate_stubs_flag: Generate C# stubs for game-specific types
    """
    game_dir = Path(game_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Load game data
    click.echo("Loading game data...")
    db = GameDatabase()
    db.load(game_dir)
    click.echo(f"  Loaded {db.total_assets} assets across {len(db.list_types())} types")

    # Auto-detect game name
    if game_name is None:
        game_name = _detect_game_name(db.game_config)
    click.echo(f"  Project name: {game_name}")

    # Step 2: Clone or link engine
    if not skip_engine:
        if engine_path:
            click.echo(f"Using existing engine at {engine_path}")
            dest = output_dir / "murder"
            if not dest.exists():
                dest.symlink_to(Path(engine_path).resolve())
        else:
            click.echo(f"Cloning Murder engine ({engine_version})...")
            clone_engine(output_dir, engine_version)
            click.echo("  Engine cloned with submodules")

    # Step 3: Create project scaffold
    click.echo("Generating project scaffold...")
    generate_solution(output_dir, game_name)

    # Step 4: Set up resource directories
    game_src_dir = output_dir / "src" / game_name
    resources_dir = game_src_dir / "resources"
    resources_dir.mkdir(parents=True, exist_ok=True)

    # Step 5: Split packed assets into individual .json files
    click.echo("Splitting packed assets into individual files...")
    counts = split_assets(db, resources_dir)
    total_written = sum(counts.values())
    click.echo(f"  Wrote {total_written} asset files across {len(counts)} directories")

    # Step 6: Copy game_config
    src_config = game_dir / "resources" / "game_config"
    if src_config.exists():
        config = load_json(src_config)
        # Optionally remap RoadGameProfile → GameProfile for editor compat
        if config.get("$type") == "Road.Assets.RoadGameProfile":
            config["$type"] = "Murder.Assets.GameProfile"
        save_json(config, resources_dir / "game_config")
        click.echo("  Copied game_config (remapped $type for editor compatibility)")

    # Step 7: Copy resource directories (atlas, fonts, shaders, sounds, images, video)
    click.echo("Copying resource files...")
    _copy_resource_dirs(game_dir, resources_dir)

    # Step 8: Copy packed data (for game runtime)
    packed_dir = game_src_dir / "packed" / "content"
    packed_dir.mkdir(parents=True, exist_ok=True)
    content_dir = game_dir / "resources" / "content"
    if content_dir.exists():
        for gz_file in content_dir.glob("*.gz"):
            shutil.copy2(gz_file, packed_dir / gz_file.name)
    click.echo("  Copied packed data to packed/content/")

    # Step 9: Generate editor_config
    game_source_path = str(game_src_dir.relative_to(output_dir))
    generate_editor_config(
        output_dir / "editor_config",
        game_source_path,
    )
    click.echo("  Generated editor_config")

    # Step 10: Generate C# stubs for game-specific types
    if generate_stubs_flag:
        stubs_dir = game_src_dir / "Generated"
        click.echo("Generating C# stubs for game-specific types...")
        stub_count = generate_stubs(db, stubs_dir)
        click.echo(f"  Generated {stub_count} stub classes")

    # Step 11: Create empty resources dir for raw assets
    (output_dir / "resources").mkdir(exist_ok=True)

    click.echo(f"\nRecovery complete! Project at: {output_dir}")
    click.echo(f"  To open in editor: cd {output_dir}/src/{game_name}.Editor && dotnet run")


def _detect_game_name(game_config: dict[str, Any]) -> str:
    """Try to detect a reasonable project name from game_config."""
    name = game_config.get("Name", "")
    if name and name != "Game Profile":
        return name.replace(" ", "")
    # Fallback
    return "RecoveredGame"


def _copy_resource_dirs(game_dir: Path, resources_dir: Path) -> None:
    """Copy atlas, fonts, shaders, sounds, images, video from game export."""
    dirs_to_copy = ["atlas", "fonts", "shaders", "sounds", "images", "video"]
    src_resources = game_dir / "resources"

    for dirname in dirs_to_copy:
        src = src_resources / dirname
        if src.exists():
            dst = resources_dir / dirname
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
