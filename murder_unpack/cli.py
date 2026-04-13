"""Click-based CLI for murder-unpack toolkit."""

from __future__ import annotations

from pathlib import Path

import click

from murder_unpack.plugins.registry import PluginRegistry

# Global plugin registry
_registry = PluginRegistry()


@click.group()
@click.version_option(package_name="murder-unpack")
@click.pass_context
def main(ctx: click.Context) -> None:
    """Murder Engine game unpacker, recovery, and modding toolkit."""
    _registry.discover_all()
    # Register plugin commands after discovery
    for cmd_name, cmd_obj in _registry.commands.items():
        if hasattr(cmd_obj, "run"):
            main.add_command(click.Command(
                name=cmd_name, callback=cmd_obj.run,
                help=getattr(cmd_obj, "help", ""),
            ))


# ─── info ────────────────────────────────────────────────────────────────────


@main.command()
@click.argument("game_dir", type=click.Path(exists=True, path_type=Path))
def info(game_dir: Path) -> None:
    """Show game info and asset counts."""
    from murder_unpack.extract.game_data import GameDatabase

    db = GameDatabase()
    db.load(game_dir)

    from murder_unpack.recover.engine_manager import detect_engine_version

    config = db.game_config
    detected_version = detect_engine_version(config)
    click.echo(f"Game Config Type: {config.get('$type', 'N/A')}")
    click.echo(f"Engine Version: {detected_version} (detected)")
    click.echo(f"Start Scene: {config.get('StartingScene', 'N/A')}")
    click.echo(f"Target FPS: {config.get('TargetFps', 'N/A')}")
    click.echo(f"Grid Size: {config.get('DefaultGridCellSize', 'N/A')}")
    click.echo(f"\nTotal Assets: {db.total_assets}")
    click.echo(f"Data Files: {db.total_packed_data}")
    click.echo(f"\nAsset Types:")
    for type_name, count in db.list_types().items():
        click.echo(f"  {type_name}: {count}")

    atlases = db.get_atlas_names(game_dir)
    if atlases:
        click.echo(f"\nAtlases: {', '.join(atlases)}")


# ─── extract-data ────────────────────────────────────────────────────────────


@main.command("extract-data")
@click.argument("game_dir", type=click.Path(exists=True, path_type=Path))
@click.argument("output_dir", type=click.Path(path_type=Path))
def extract_data(game_dir: Path, output_dir: Path) -> None:
    """Dump all .gz data files as plain JSON."""
    from murder_unpack.core.gzip_json import decompress_gz_json, save_json

    output_dir.mkdir(parents=True, exist_ok=True)
    content_dir = game_dir / "resources" / "content"

    for gz_file in sorted(content_dir.glob("*.gz")):
        click.echo(f"Extracting {gz_file.name}...")
        data = decompress_gz_json(gz_file)
        out_path = output_dir / f"{gz_file.stem}.json"
        save_json(data, out_path)

    click.echo(f"Done! JSON files written to {output_dir}")


# ─── extract-sprites ─────────────────────────────────────────────────────────


@main.command("extract-sprites")
@click.argument("game_dir", type=click.Path(exists=True, path_type=Path))
@click.argument("output_dir", type=click.Path(path_type=Path))
@click.option("--atlas", default=None, help="Extract from specific atlas only")
@click.option("--no-untrim", is_flag=True, help="Don't reconstruct original size")
def extract_sprites(game_dir: Path, output_dir: Path, atlas: str | None, no_untrim: bool) -> None:
    """Extract all sprites from atlas sheets as PNG files."""
    from murder_unpack.extract.game_data import GameDatabase
    from murder_unpack.extract.sprite_extractor import SpriteExtractor

    atlas_dir = game_dir / "resources" / "atlas"
    extractor = SpriteExtractor(atlas_dir)

    db = GameDatabase()
    db.load(game_dir)
    atlas_names = [atlas] if atlas else db.get_atlas_names(game_dir)

    total = 0
    for name in atlas_names:
        click.echo(f"Extracting atlas '{name}'...")
        count = extractor.extract_all_from_atlas(name, output_dir / name, untrim=not no_untrim)
        click.echo(f"  {count} sprites extracted")
        total += count

    click.echo(f"\nTotal: {total} sprites extracted to {output_dir}")


# ─── extract-dialogue ────────────────────────────────────────────────────────


@main.command("extract-dialogue")
@click.argument("game_dir", type=click.Path(exists=True, path_type=Path))
@click.argument("output_dir", type=click.Path(path_type=Path))
@click.option("--format", "fmt", type=click.Choice(["gum", "markdown", "both"]), default="both",
              help="Output format: gum (Murder's script format), markdown, or both")
def extract_dialogue(game_dir: Path, output_dir: Path, fmt: str) -> None:
    """Export all dialogue scripts (default: both .gum and .md formats)."""
    from murder_unpack.extract.game_data import GameDatabase

    db = GameDatabase()
    db.load(game_dir)

    if fmt in ("gum", "both"):
        from murder_unpack.extract.gum_exporter import export_dialogues_gum
        gum_dir = output_dir / "gum" if fmt == "both" else output_dir
        count = export_dialogues_gum(db, gum_dir)
        click.echo(f"Exported {count} .gum scripts to {gum_dir}")

    if fmt in ("markdown", "both"):
        from murder_unpack.extract.dialogue_extractor import extract_dialogues
        md_dir = output_dir / "markdown" if fmt == "both" else output_dir
        count = extract_dialogues(db, md_dir)
        click.echo(f"Exported {count} markdown dialogues to {md_dir}")


# ─── list-assets ─────────────────────────────────────────────────────────────


@main.command("list-assets")
@click.argument("game_dir", type=click.Path(exists=True, path_type=Path))
@click.option("--type", "type_filter", default=None, help="Filter by $type (substring)")
@click.option("--name", "name_filter", default=None, help="Filter by name (substring)")
def list_assets(game_dir: Path, type_filter: str | None, name_filter: str | None) -> None:
    """List all assets in the game data."""
    from murder_unpack.extract.game_data import GameDatabase

    db = GameDatabase()
    db.load(game_dir)

    for asset in db.all_assets():
        type_name = asset.get("$type", "?")
        name = asset.get("Name", "?")
        guid = asset.get("Guid", "?")

        if type_filter and type_filter.lower() not in type_name.lower():
            continue
        if name_filter and name_filter.lower() not in name.lower():
            continue

        short_type = type_name.rsplit(".", 1)[-1]
        click.echo(f"[{short_type}] {name} ({guid})")


# ─── decode-qoi ──────────────────────────────────────────────────────────────


@main.command("decode-qoi")
@click.argument("input_path", type=click.Path(exists=True, path_type=Path))
@click.argument("output_path", type=click.Path(path_type=Path))
def decode_qoi(input_path: Path, output_path: Path) -> None:
    """Convert a .qoi.gz file to PNG."""
    from murder_unpack.core.qoi import decode_qoi_gz

    img = decode_qoi_gz(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)
    click.echo(f"Decoded {input_path.name} → {output_path} ({img.width}x{img.height})")


# ─── recover ─────────────────────────────────────────────────────────────────


@main.command()
@click.argument("game_dir", type=click.Path(exists=True, path_type=Path))
@click.argument("output_dir", type=click.Path(path_type=Path))
@click.option("--engine-version", default=None, help="Engine branch/tag/commit (auto-detected if omitted)")
@click.option("--engine-path", type=click.Path(path_type=Path), default=None, help="Use existing engine clone")
@click.option("--skip-engine", is_flag=True, help="Don't clone engine")
@click.option("--game-name", default=None, help="Project name (auto-detected from game assembly)")
@click.option("--no-stubs", is_flag=True, help="Don't generate C# stubs")
@click.option("--decompile-timeout", type=int, default=600,
              help="Timeout in seconds for C# decompilation (default: 600)")
@click.option("--game-fix", default=None,
              help="Apply per-game decompiler fixes (auto-detected if omitted, 'none' to skip)")
def recover(
    game_dir: Path, output_dir: Path,
    engine_version: str, engine_path: Path | None,
    skip_engine: bool, game_name: str | None, no_stubs: bool,
    decompile_timeout: int, game_fix: str | None,
) -> None:
    """Recover exported game into a Murder Engine editor project."""
    from murder_unpack.recover.project_recovery import recover_project

    recover_project(
        game_dir=game_dir,
        output_dir=output_dir,
        game_name=game_name,
        engine_version=engine_version,
        engine_path=engine_path,
        skip_engine=skip_engine,
        generate_stubs_flag=not no_stubs,
        decompile_timeout=decompile_timeout,
        game_fix_id=game_fix,
    )


# ─── analyze-binary ──────────────────────────────────────────────────────────


@main.command("analyze-binary")
@click.argument("exe_path", type=click.Path(exists=True, path_type=Path))
@click.option("--extract-assemblies", type=click.Path(path_type=Path), default=None,
              help="Extract .dlls from single-file bundle")
@click.option("--decompile", type=click.Path(path_type=Path), default=None,
              help="Decompile to C# source (needs dotnet SDK)")
@click.option("--namespace", default="", help="Namespace prefix to scan for (auto-detected if omitted)")
def analyze_binary(
    exe_path: Path,
    extract_assemblies: Path | None,
    decompile: Path | None,
    namespace: str,
) -> None:
    """Analyze game executable — detect format, extract types."""
    from murder_unpack.binary.detect import detect_binary

    info = detect_binary(exe_path)
    click.echo(f"Format: {info.exe_format.value}")
    click.echo(f"Platform: {info.platform.value}")
    click.echo(f"Deployment: {info.deployment.value}")
    click.echo(f"NativeAOT: {info.is_native_aot}")
    click.echo(f"Single-file bundle: {info.is_single_file_bundle}")
    if info.bundle_file_count is not None:
        click.echo(f"Bundle files: {info.bundle_file_count}")
    if info.is_single_file_bundle:
        click.echo(f"Managed assemblies in bundle: {info.has_managed_assemblies}")
    if info.has_clr:
        click.echo(f"CLR header: {info.has_clr}")

    # Extract type names from binary
    from murder_unpack.binary.native_strings import extract_type_names
    types = extract_type_names(exe_path, namespace)
    detected_ns = namespace or "(auto-detected)"
    click.echo(f"\n{detected_ns}* types found: {types.total}")
    click.echo(f"  Assets: {len(types.assets)}")
    click.echo(f"  Components: {len(types.components)}")
    click.echo(f"  Systems: {len(types.systems)}")
    click.echo(f"  Services: {len(types.services)}")
    click.echo(f"  State Machines: {len(types.state_machines)}")
    click.echo(f"  Interactions: {len(types.interactions)}")
    click.echo(f"  Other: {len(types.other)}")

    # Extract assemblies from bundle
    if extract_assemblies is not None:
        from murder_unpack.binary.bundle_extractor import extract_bundle
        try:
            extracted = extract_bundle(exe_path, extract_assemblies)
            click.echo(f"\nExtracted {len(extracted)} files to {extract_assemblies}")
        except ValueError as e:
            click.echo(f"\n{e}")

    # Decompile
    if decompile is not None:
        from murder_unpack.binary.decompiler import (
            decompile_assembly,
            decompile_with_helper,
            find_game_assembly,
            is_dotnet_available,
            is_ilspycmd_available,
        )
        if not is_dotnet_available():
            click.echo("\ndotnet SDK not found — required for decompilation")
            return

        ref_dir = extract_assemblies if extract_assemblies else exe_path.parent
        game_dll = find_game_assembly(ref_dir)

        if game_dll:
            click.echo(f"\nDecompiling {game_dll.name}...")
            success = decompile_with_helper(
                game_dll, decompile, reference_dir=ref_dir,
            )
            if not success and is_ilspycmd_available():
                click.echo("Retrying with ilspycmd...")
                success = decompile_assembly(game_dll, decompile)
            if success:
                click.echo(f"Decompiled to {decompile}")
            else:
                click.echo("Decompilation failed")
        else:
            click.echo("\nNo game assembly found to decompile")


# ─── engine-versions ─────────────────────────────────────────────────────────


@main.command("engine-versions")
def engine_versions() -> None:
    """List available Murder Engine versions (branches and tags)."""
    from murder_unpack.recover.engine_manager import list_versions

    click.echo("Fetching versions from GitHub...")
    versions = list_versions()

    click.echo("\nRelease branches:")
    for b in versions["branches"]:
        if b.startswith("rel/"):
            click.echo(f"  {b}")

    click.echo("\nDev branches:")
    for b in versions["branches"]:
        if not b.startswith("rel/") and b != "main":
            click.echo(f"  {b}")

    click.echo(f"\nmain (latest development)")

    if versions["tags"]:
        click.echo("\nTags:")
        for t in versions["tags"]:
            click.echo(f"  {t}")


# ─── repack ──────────────────────────────────────────────────────────────────


@main.command()
@click.argument("project_dir", type=click.Path(exists=True, path_type=Path))
@click.argument("output_dir", type=click.Path(path_type=Path))
def repack(project_dir: Path, output_dir: Path) -> None:
    """Repack modified assets back into .gz format."""
    from murder_unpack.repack.repacker import repack_assets

    click.echo(f"Repacking assets from {project_dir}...")
    repack_assets(project_dir, output_dir)
    click.echo(f"Done! Packed files written to {output_dir}")


# ─── extract-all ─────────────────────────────────────────────────────────────


@main.command("extract-all")
@click.argument("game_dir", type=click.Path(exists=True, path_type=Path))
@click.argument("output_dir", type=click.Path(path_type=Path))
def extract_all(game_dir: Path, output_dir: Path) -> None:
    """Full extraction: data, sprites, dialogues (.gum + markdown), and localization."""
    from murder_unpack.core.gzip_json import decompress_gz_json, save_json
    from murder_unpack.extract.dialogue_extractor import extract_dialogues
    from murder_unpack.extract.game_data import GameDatabase
    from murder_unpack.extract.gum_exporter import export_dialogues_gum
    from murder_unpack.extract.sprite_extractor import SpriteExtractor
    from murder_unpack.recover.project_recovery import export_localization_csv

    db = GameDatabase()
    db.load(game_dir)

    # Extract JSON data
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    content_dir = game_dir / "resources" / "content"
    for gz_file in sorted(content_dir.glob("*.gz")):
        data = decompress_gz_json(gz_file)
        save_json(data, data_dir / f"{gz_file.stem}.json")
    click.echo(f"Extracted JSON data to {data_dir}")

    # Extract sprites
    atlas_dir = game_dir / "resources" / "atlas"
    if atlas_dir.exists():
        sprites_dir = output_dir / "sprites"
        extractor = SpriteExtractor(atlas_dir)
        total = 0
        for name in db.get_atlas_names(game_dir):
            count = extractor.extract_all_from_atlas(name, sprites_dir / name)
            total += count
        click.echo(f"Extracted {total} sprites to {sprites_dir}")

    # Extract dialogues — .gum (editor native) first, then markdown
    dialogue_dir = output_dir / "dialogues"
    gum_count = export_dialogues_gum(db, dialogue_dir / "gum")
    click.echo(f"Exported {gum_count} .gum scripts to {dialogue_dir / 'gum'}")
    md_count = extract_dialogues(db, dialogue_dir / "markdown")
    click.echo(f"Exported {md_count} markdown dialogues to {dialogue_dir / 'markdown'}")

    # Extract localization CSV (editor native format)
    loc_dir = output_dir / "localization"
    loc_count = export_localization_csv(db, loc_dir)
    click.echo(f"Exported {loc_count} localization CSV files to {loc_dir}")


# ─── plugins ─────────────────────────────────────────────────────────────────


@main.group()
def plugins() -> None:
    """Manage plugins."""
    pass


@plugins.command("list")
def plugins_list() -> None:
    """List loaded plugins."""
    loaded = _registry.list_plugins()
    if not loaded:
        click.echo("No plugins loaded.")
        return
    for category, names in loaded.items():
        click.echo(f"\n{category}:")
        for name in names:
            click.echo(f"  - {name}")


@plugins.command("dir")
def plugins_dir() -> None:
    """Show plugin directories."""
    for d in _registry.plugin_dirs():
        exists = "exists" if d.exists() else "not found"
        click.echo(f"  {d} ({exists})")
