"""Full editor project recovery orchestrator.

Reverses the Murder Engine export process: unpacks .gz data files,
splits assets into individual .json files, creates a C# project scaffold,
and clones the engine at the auto-detected (or specified) version.

Recovery includes:
- Auto-detected engine version from game_config field fingerprint
- Individual .json asset files in correct editor directories
- .gum dialogue scripts reconstructed from compiled CharacterAsset data
- Localization CSV files for each language
- All resource files and directories (atlas, fonts, shaders, sounds, images, video, fmod, icons)
- C# project scaffold (.sln, .csproj, Program.cs) matching hellomurder template
- Auto-generated C# stubs for game-specific types
- editor_config auto-created by Murder editor on first run
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import click

from murder_unpack.core.gzip_json import load_json, save_json
from murder_unpack.extract.game_data import GameDatabase
from murder_unpack.recover.asset_splitter import (
    detect_game_assembly,
    remap_assembly_names,
    split_assets,
)
from murder_unpack.recover.engine_manager import clone_engine, detect_engine_version
from murder_unpack.recover.scaffold import generate_solution
from murder_unpack.recover.stub_generator import generate_stubs


def recover_project(
    game_dir: Path | str,
    output_dir: Path | str,
    game_name: str | None = None,
    engine_version: str | None = None,
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

    # Auto-detect game name from original assembly, then game_config
    if game_name is None:
        game_name = detect_game_assembly(db) or _detect_game_name(db.game_config)
    click.echo(f"  Project name: {game_name}")

    # Auto-detect engine version from game_config if not specified
    if engine_version is None and not skip_engine and engine_path is None:
        engine_version = detect_engine_version(db.game_config)
        click.echo(f"  Auto-detected engine version: {engine_version}")
    elif engine_version is None:
        engine_version = "main"

    # Step 2: Clone or link engine
    if not skip_engine:
        if engine_path:
            click.echo(f"Copying engine from {engine_path}...")
            dest = output_dir / "murder"
            if not dest.exists():
                # Copy instead of symlink — dotnet resolves relative paths
                # from symlink target, breaking Bang/Gum submodule references
                shutil.copytree(
                    Path(engine_path).resolve(), dest,
                    symlinks=True, dirs_exist_ok=False,
                )
        else:
            click.echo(f"Cloning Murder engine ({engine_version})...")
            clone_engine(output_dir, engine_version)
            click.echo("  Engine cloned with submodules")

    # Step 3: Patch engine for recovery compatibility
    _patch_engine(output_dir)

    # Step 4: Create project scaffold
    click.echo("Generating project scaffold...")
    generate_solution(output_dir, game_name)

    # Step 5: Set up resource directories
    game_src_dir = output_dir / "src" / game_name
    resources_dir = game_src_dir / "resources"
    resources_dir.mkdir(parents=True, exist_ok=True)

    # Step 6: Detect original assembly name and remap if needed
    assembly_remap = None
    original_assembly = detect_game_assembly(db)
    if original_assembly and original_assembly != game_name:
        assembly_remap = (original_assembly, game_name)
        click.echo(f"  Remapping assembly: {original_assembly} → {game_name}")

    # Step 7: Split packed assets into individual .json files
    click.echo("Splitting packed assets into individual files...")
    counts = split_assets(db, resources_dir, assembly_remap=assembly_remap)
    total_written = sum(counts.values())
    click.echo(f"  Wrote {total_written} asset files across {len(counts)} directories")

    # Step 8: Copy game_config
    src_config = game_dir / "resources" / "game_config"
    if src_config.exists():
        config = load_json(src_config)
        if config.get("$type") == "Road.Assets.RoadGameProfile":
            config["$type"] = "Murder.Assets.GameProfile"
        if assembly_remap:
            config = remap_assembly_names(config, *assembly_remap)
        save_json(config, resources_dir / "game_config")
        click.echo("  Copied game_config")

    # Step 9: Copy ALL resource directories
    click.echo("Copying resource files...")
    _copy_resources(game_dir, resources_dir)

    # Step 10: Copy packed data (for game runtime)
    packed_dir = game_src_dir / "packed" / "content"
    packed_dir.mkdir(parents=True, exist_ok=True)
    content_dir = game_dir / "resources" / "content"
    if content_dir.exists():
        for gz_file in content_dir.glob("*.gz"):
            shutil.copy2(gz_file, packed_dir / gz_file.name)
    click.echo("  Copied packed data to packed/content/")

    # Note: editor_config is auto-generated by the Murder editor on first run.
    # It uses Game.Data.GameDirectory (= IMurderGame.Name) to compute paths.
    # No need to pre-create it.

    # Step 11: Generate C# stubs for game-specific types
    if generate_stubs_flag:
        stubs_dir = game_src_dir / "Generated"
        click.echo("Generating C# stubs for game-specific types...")
        stub_count = generate_stubs(db, stubs_dir)
        click.echo(f"  Generated {stub_count} stub classes")

    # Step 12: Reconstruct .gum dialogue scripts
    click.echo("Reconstructing .gum dialogue scripts...")
    raw_resources_dir = output_dir / "resources"
    raw_resources_dir.mkdir(exist_ok=True)
    gum_count = _export_gum_scripts(db, raw_resources_dir / "dialogues")
    click.echo(f"  Reconstructed {gum_count} .gum scripts")

    # Step 13: Export localization CSV files
    click.echo("Exporting localization CSV files...")
    loc_count = export_localization_csv(db, raw_resources_dir / "loc")
    click.echo(f"  Exported {loc_count} localization CSV files")

    click.echo(f"\nRecovery complete! Project at: {output_dir}")
    click.echo(f"  To open in editor: cd {output_dir}/src/{game_name}.Editor && dotnet run")


def _patch_engine(output_dir: Path) -> None:
    """Apply compatibility patches to the Murder engine for recovered projects.

    Patches GetAsset to log warnings instead of throwing when assets are
    missing. Recovered projects may have assets that fail to deserialize
    (due to game-specific types), so hard crashes on missing GUIDs would
    make the editor unusable.
    """
    # Patch JsonTypeConverter to return typeof(object) instead of throwing
    # when a type can't be resolved. This is the root cause of most
    # deserialization failures — game-specific types like Road.Systems.*
    # throw JsonException, killing the entire asset load.
    jtc_path = output_dir / "murder/src/Murder/Utilities/Serialization/JsonTypeConverter.cs"
    if jtc_path.exists():
        jtc_src = jtc_path.read_text(encoding="utf-8")
        old_throw = (
            '            // TODO: Do something smarter that converts previous types into new ones?\n'
            '            throw new JsonException($"Type {assemblyQualifiedName} not found!");'
        )
        new_return = (
            '            GameLogger.Warning($"Type not found: {assemblyQualifiedName}");\n'
            '            return typeof(object);'
        )
        if old_throw in jtc_src:
            jtc_src = jtc_src.replace(old_throw, new_return)
            # Add GameLogger import if not present
            if "using Murder.Diagnostics;" not in jtc_src:
                jtc_src = jtc_src.replace(
                    "using Murder.Utilities;",
                    "using Murder.Diagnostics;\nusing Murder.Utilities;",
                )
            jtc_path.write_text(jtc_src, encoding="utf-8")
            click.echo("  Patched engine: JsonTypeConverter gracefully handles missing types")

    # Patch GetAsset to return empty placeholders instead of throwing.
    # Even with better deserialization, some assets may still not load.
    # Throwing here propagates through ImGui draw code, corrupting its
    # Begin/End state stack and causing native SEGV.
    gdm_path = output_dir / "murder/src/Murder/Data/GameDataManager.cs"
    if gdm_path.exists():
        gdm_src = gdm_path.read_text(encoding="utf-8")

        old_generic = 'throw new ArgumentException($"Unable to find the asset of type {typeof(T).Name} with id: {id} in database.");'
        new_generic = (
            'GameLogger.Warning($"Unable to find the asset of type {typeof(T).Name} with id: {id} in database.");\n'
            '            try { return System.Activator.CreateInstance<T>(); } catch { }\n'
            '            return default!;'
        )

        old_nongeneric = 'throw new ArgumentException($"Unable to find the asset with id: {id} in database.");'
        new_nongeneric = (
            'GameLogger.Warning($"Unable to find the asset with id: {id} in database.");\n'
            '            return default!;'
        )

        patched = False
        if old_generic in gdm_src:
            gdm_src = gdm_src.replace(old_generic, new_generic)
            patched = True
        if old_nongeneric in gdm_src:
            gdm_src = gdm_src.replace(old_nongeneric, new_nongeneric)
            patched = True
        if patched:
            gdm_path.write_text(gdm_src, encoding="utf-8")
            click.echo("  Patched engine: GetAsset returns placeholders for missing assets")

    # Patch Entity.cs — two fixes:
    # 1. Array resize for large component indices
    # 2. CheckForRequiredComponents: warn instead of Debug.Assert (which
    #    terminates the process). Recovered entities have incomplete
    #    components because some game-specific types resolve to object.
    entity_path = output_dir / "murder/bang/src/Bang/Entities/Entity.cs"
    if entity_path.exists():
        entity_src = entity_path.read_text(encoding="utf-8")
        patched = False

        old_resize = "bool[] newLookup = new bool[_availableComponents.Length * 2];"
        new_resize = "int newSize = Math.Max(_availableComponents.Length * 2, index + 1);\n                bool[] newLookup = new bool[newSize];"
        if old_resize in entity_src:
            entity_src = entity_src.replace(old_resize, new_resize)
            patched = True

        old_assert = (
            '                        Debug.Assert(!report,\n'
            '                            $"Missing {requiredType.Name} required by {t.Name} in entity declaration!");'
        )
        new_warn = (
            '                        if (report)\n'
            '                        {\n'
            '                            System.Console.Error.WriteLine(\n'
            '                                $"Warning: Missing {requiredType.Name} required by {t.Name} in entity declaration!");\n'
            '                        }'
        )
        if old_assert in entity_src:
            entity_src = entity_src.replace(old_assert, new_warn)
            patched = True

        if patched:
            entity_path.write_text(entity_src, encoding="utf-8")
            click.echo("  Patched engine: Entity array resize and component requirement checks")


def _detect_game_name(game_config: dict[str, Any]) -> str:
    """Fallback game name detection from game_config Name field."""
    name = game_config.get("Name", "")
    if name and name != "Game Profile":
        return name.replace(" ", "")
    return "RecoveredGame"


def _copy_resources(game_dir: Path, resources_dir: Path) -> None:
    """Copy all resource directories and standalone files from game export.

    Copies all subdirectories (atlas, fonts, shaders, sounds, images, video,
    fmod, etc.) and all standalone files (icons, manifests, etc.) from the
    game's resources/ directory. Skips content/ (handled separately as packed
    data) and game_config (handled separately with type remapping).
    """
    src_resources = game_dir / "resources"
    skip_dirs = {"content"}  # Packed data handled separately
    skip_files = {"game_config"}  # Handled separately with type remapping

    # Copy all subdirectories
    for item in sorted(src_resources.iterdir()):
        if item.is_dir() and item.name not in skip_dirs:
            dst = resources_dir / item.name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(item, dst)

    # Copy all standalone files at resources/ root
    for item in sorted(src_resources.iterdir()):
        if item.is_file() and item.name not in skip_files:
            shutil.copy2(item, resources_dir / item.name)


def _export_gum_scripts(db: GameDatabase, output_dir: Path) -> int:
    """Reconstruct .gum dialogue scripts from CharacterAsset data."""
    from murder_unpack.extract.gum_exporter import export_dialogues_gum
    return export_dialogues_gum(db, output_dir)


def export_localization_csv(db: GameDatabase, output_dir: Path) -> int:
    """Export localization assets as CSV files matching Murder's editor format.

    Murder's editor exports localization as CSV with columns:
    Guid, Speaker, Original, Translated, Notes

    Dialogue resources are grouped by CharacterAsset name.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build speaker name lookup
    speaker_names: dict[str, str] = {}
    for s in db.get_by_type("Road.Assets.RoadSpeakerAsset"):
        speaker_names[s.get("Guid", "")] = s.get("Name", "")
    for s in db.get_by_type("Murder.Assets.Dialogs.SpeakerAsset"):
        speaker_names[s.get("Guid", "")] = s.get("Name", "")

    # Build CharacterAsset name lookup
    char_names: dict[str, str] = {}
    for c in db.get_by_type("Murder.Assets.CharacterAsset"):
        char_names[c.get("Guid", "")] = c.get("Name", "")

    locs = db.get_by_type("Murder.Assets.Localization.LocalizationAsset")
    count = 0

    for loc in locs:
        name = loc.get("Name", f"loc_{count}")
        safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
        out_path = output_dir / f"{safe_name}.csv"

        lines: list[str] = []
        # CSV header
        lines.append("Guid,Speaker,Original,Translated,Notes")

        # Regular resources
        resources = loc.get("resources", [])
        for entry in resources:
            guid = entry.get("Guid", "")
            text = entry.get("String", "")
            notes = entry.get("Notes", "")
            is_generated = entry.get("IsGenerated", False)
            # Escape CSV fields
            text_csv = _csv_escape(text)
            notes_csv = _csv_escape(notes)
            lines.append(f"{guid},,{text_csv},{text_csv},{notes_csv}")

        # Dialogue resources (grouped by CharacterAsset)
        dialogue_resources = loc.get("dialogueResources", [])
        for dlg_group in dialogue_resources:
            dlg_guid = dlg_group.get("DialogueResourceGuid", "")
            char_name = char_names.get(dlg_guid, dlg_guid[:8])
            lines.append(f"# {char_name}")

            for data_res in dlg_group.get("DataResources", []):
                guid = data_res.get("Guid", "")
                speaker_guid = data_res.get("Speaker", "")
                speaker_name = speaker_names.get(speaker_guid, speaker_guid[:8] if speaker_guid else "")
                # Look up the actual text from resources
                text = ""
                for r in resources:
                    if r.get("Guid") == guid:
                        text = r.get("String", "")
                        break
                text_csv = _csv_escape(text)
                lines.append(f"{guid},{_csv_escape(speaker_name)},{text_csv},{text_csv},")

        out_path.write_text("\n".join(lines), encoding="utf-8")
        count += 1

    return count


def _csv_escape(value: str) -> str:
    """Escape a value for CSV output."""
    if not value:
        return ""
    if "," in value or '"' in value or "\n" in value:
        return '"' + value.replace('"', '""') + '"'
    return value
