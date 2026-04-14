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
- Full C# decompilation via bundled per-type decompiler (managed single-file bundles)
- Fallback: auto-generated C# stubs for game-specific types (NativeAOT games)
- Decompiler compat: init→set (trial-build-targeted), readonly removal, JsonStringEnumConverter
- Per-game fixes via auto-detected fix registry
- GetAsset crash prevention (both modes), stub-only patches for missing types
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
from murder_unpack.recover.native_libs import (
    check_arm64_readiness,
    is_arm64_windows,
    setup_arm64_workaround,
)
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
    decompile_timeout: int = 600,
    game_fix_id: str | None = None,
    engine_repo: str | None = None,
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
        decompile_timeout: Timeout in seconds for C# decompilation
        game_fix_id: Per-game fix ID (auto-detected if None, "none" to skip)
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
        original_assembly = detect_game_assembly(db)
        engine_version = detect_engine_version(
            db.game_config,
            assembly_name=original_assembly,
            db=db,
            game_dir=game_dir,
        )
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
            clone_engine(output_dir, engine_version, repo=engine_repo)
            click.echo("  Engine cloned with submodules")

    # Step 2b: Check for EOL target frameworks in engine
    engine_dir = output_dir / "murder"
    if engine_dir.is_dir():
        eol_tfm = _check_eol_frameworks(engine_dir)
        if eol_tfm:
            click.echo(f"  WARNING: Engine targets {eol_tfm} (EOL). Install the runtime:")
            click.echo(f"    dotnet workload install {eol_tfm} OR download from https://dotnet.microsoft.com/download/dotnet")

    # Step 3: Create project scaffold
    click.echo("Generating project scaffold...")
    generate_solution(output_dir, game_name)

    # Step 3b: Handle ARM64 Windows — Murder.FNA has no ARM64 native libs
    if is_arm64_windows():
        click.echo("Detected ARM64 Windows — configuring x64 build workaround...")
        setup_arm64_workaround(output_dir)
        check_arm64_readiness(output_dir)

    # Step 4: Set up resource directories
    game_src_dir = output_dir / "src" / game_name
    resources_dir = game_src_dir / "resources"
    resources_dir.mkdir(parents=True, exist_ok=True)

    # Step 5: Detect original assembly name and remap if needed
    assembly_remap = None
    original_assembly = detect_game_assembly(db)
    if original_assembly and original_assembly != game_name:
        assembly_remap = (original_assembly, game_name)
        click.echo(f"  Remapping assembly: {original_assembly} → {game_name}")

    # Step 6: Split packed assets into individual .json files
    click.echo("Splitting packed assets into individual files...")
    counts = split_assets(db, resources_dir, assembly_remap=assembly_remap)
    total_written = sum(counts.values())
    click.echo(f"  Wrote {total_written} asset files across {len(counts)} directories")

    # Step 7: Copy game_config (type remapping deferred to after decompilation)
    # Some games ship game_config.json (with extension), others game_config (without)
    src_config = None
    for config_name in ("game_config.json", "game_config"):
        candidate = game_dir / "resources" / config_name
        if candidate.exists():
            src_config = candidate
            break
    if src_config is not None:
        config = load_json(src_config)
        if assembly_remap:
            config = remap_assembly_names(config, *assembly_remap)
        save_json(config, resources_dir / "game_config")
        click.echo("  Copied game_config")

    # Step 8: Copy ALL resource directories
    click.echo("Copying resource files...")
    _copy_resources(game_dir, resources_dir)

    # Step 9: Copy packed data (for game runtime)
    content_dir = game_dir / "resources" / "content"
    if content_dir.exists():
        packed_dir = game_src_dir / "packed" / "content"
        packed_dir.mkdir(parents=True, exist_ok=True)
        for gz_file in content_dir.glob("*.gz"):
            shutil.copy2(gz_file, packed_dir / gz_file.name)
        click.echo("  Copied packed data to packed/content/")

    # Note: editor_config is auto-generated by the Murder editor on first run.
    # It uses Game.Data.GameDirectory (= IMurderGame.Name) to compute paths.
    # No need to pre-create it.

    # Step 10: Recover C# source — decompile managed assemblies or generate stubs
    decompiled = False
    if generate_stubs_flag:
        decompiled = _try_decompile_game(game_dir, game_src_dir, decompile_timeout)
        if not decompiled:
            stubs_dir = game_src_dir / "Generated"
            click.echo("Generating C# stubs for game-specific types...")
            stub_count = generate_stubs(db, stubs_dir)
            click.echo(f"  Generated {stub_count} stub classes")

    # Step 10b: Handle decompiled source-generator output.
    # Modern engines (with Bang.Generator) regenerate these at build time,
    # so we delete the decompiled copies to avoid CS0111 duplicates.
    # Older engines (with Murder.Generator post-build tool) need the decompiled
    # copies as seed files since the tool only runs after a successful build.
    if decompiled:
        decompiled_dir = game_src_dir / "Decompiled"
        has_bang_generator = (output_dir / "murder" / "bang" / "src" / "Bang.Generator" / "Bang.Generator.csproj").exists()
        if has_bang_generator:
            bang_dir = decompiled_dir / "Bang"
            if bang_dir.is_dir():
                shutil.rmtree(bang_dir)
        else:
            # Move generated extensions to Generated/ where the post-build
            # Generator expects to find and update them
            bang_dir = decompiled_dir / "Bang"
            gen_dir = game_src_dir / "Generated"
            if bang_dir.is_dir():
                gen_dir.mkdir(parents=True, exist_ok=True)
                for cs_file in bang_dir.rglob("*.cs"):
                    dest = gen_dir / cs_file.name
                    shutil.move(str(cs_file), str(dest))
                shutil.rmtree(bang_dir)

    # Step 11: Mode-specific setup
    if decompiled:
        _use_decompiled_game_class(output_dir, game_name, db)
        added = _add_nuget_packages(game_src_dir, game_name)
        if added:
            click.echo(f"  Added NuGet packages: {', '.join(added)}")
        count = _fix_init_from_build_errors(output_dir, game_name)
        if count:
            click.echo(f"  Decompiler compat: init→set in {count} engine files")
    else:
        _remap_game_config_type(resources_dir)
        _patch_engine(output_dir)

    # Always patch GetAsset to warn instead of throw on missing assets.
    # Needed in both modes: stubs have incomplete types, decompiled projects
    # may have fresh/empty preferences with uninitialized GUIDs.
    _patch_getasset(output_dir)

    # Step 12: Apply per-game decompiler fixes
    if decompiled:
        _apply_game_fixes(
            db, game_dir, game_src_dir / "Decompiled",
            game_fix_id, assembly_name=detect_game_assembly(db),
        )

    # Step 13: Reconstruct .gum dialogue scripts
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
    if is_arm64_windows():
        click.echo(f"  To open in editor: run-editor.cmd")
        click.echo(f"  Or: dotnet build -r win-x64 && run the x64 exe from bin/Debug/net8.0/win-x64/")
    else:
        click.echo(f"  To open in editor: cd {output_dir}/src/{game_name}.Editor && dotnet run")


def _apply_game_fixes(
    db: GameDatabase,
    game_dir: Path,
    decompiled_dir: Path,
    game_fix_id: str | None,
    assembly_name: str | None = None,
) -> None:
    """Detect and apply per-game decompiler fixes."""
    if game_fix_id == "none":
        return
    if not decompiled_dir.is_dir():
        return

    from murder_unpack.fixes import get_registry
    registry = get_registry()

    if game_fix_id:
        fix = registry.get(game_fix_id)
        if not fix:
            click.echo(f"  Unknown game fix: {game_fix_id}")
            available = ", ".join(f.id for f in registry.list_all())
            if available:
                click.echo(f"  Available: {available}")
            return
    else:
        fix = registry.detect(
            db=db, game_dir=game_dir, assembly_name=assembly_name,
        )

    if fix:
        count = fix.apply(decompiled_dir)
        if count:
            click.echo(f"  Applied game fix '{fix.id}': {count} files patched")
    else:
        click.echo("  No per-game fixes detected (use --game-fix to specify)")


def find_game_executable(game_dir: Path) -> Path | None:
    """Find the Murder Engine game executable in the game directory.

    Murder Engine exports place the game executable at the root of the
    game directory alongside resources/, DLLs (FNA3D, FAudio, SDL3), etc.
    """
    # Known Murder Engine support DLLs — not the game executable
    skip_prefixes = ("FNA", "FAudio", "SDL", "fmod", "libsteam_api", "steam_api", "libtheorafile")

    # Windows: look for .exe
    for exe in game_dir.glob("*.exe"):
        if not exe.stem.startswith(skip_prefixes):
            return exe

    # Linux: ELF binary (no extension, \x7fELF magic)
    for f in game_dir.iterdir():
        if f.is_file() and f.suffix == "":
            try:
                if f.read_bytes()[:4] == b"\x7fELF":
                    return f
            except (OSError, PermissionError):
                continue

    # macOS: Mach-O binary (no extension or inside .app bundle)
    macho_magic = {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
                   b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}
    for f in game_dir.iterdir():
        if f.is_file() and f.suffix == "":
            try:
                if f.read_bytes()[:4] in macho_magic:
                    return f
            except (OSError, PermissionError):
                continue

    return None


def _try_decompile_game(game_dir: Path, game_src_dir: Path, timeout: int = 600) -> bool:
    """Try to decompile the game executable if it contains managed assemblies.

    Uses bundled decompile-helper (per-type decompilation with timeouts) as
    the primary method. Falls back to ilspycmd if the helper can't be built.
    Returns False (triggering stub generation) if all methods fail.
    """
    from murder_unpack.binary.bundle_extractor import extract_bundle
    from murder_unpack.binary.decompiler import (
        decompile_assembly,
        decompile_with_helper,
        find_game_assembly,
        is_dotnet_available,
        is_ilspycmd_available,
    )
    from murder_unpack.binary.detect import detect_binary

    exe_path = find_game_executable(game_dir)
    if exe_path is None:
        click.echo("Analyzing game binary... no executable found")
        return False

    click.echo(f"Analyzing game binary ({exe_path.name})...")
    info = detect_binary(exe_path)
    click.echo(f"  Format: {info.exe_format.value}, Deployment: {info.deployment.value}")

    if info.is_native_aot:
        click.echo("  Binary is NativeAOT — managed IL not available, using stubs")
        return False

    if not info.is_single_file_bundle and not info.has_clr:
        click.echo("  No managed assemblies detected, using stubs")
        return False

    if not is_dotnet_available():
        click.echo("  dotnet SDK not found — required for decompilation")
        click.echo("  Falling back to stub generation")
        return False

    # Extract assemblies from single-file bundle
    if info.is_single_file_bundle:
        extract_dir = game_src_dir / ".extracted-assemblies"
        click.echo("Extracting assemblies from single-file bundle...")
        extracted = extract_bundle(exe_path, extract_dir)
        click.echo(f"  Extracted {len(extracted)} files")
        assemblies_dir = extract_dir
    else:
        assemblies_dir = exe_path.parent

    # Find the game assembly
    game_dll = find_game_assembly(assemblies_dir)
    if game_dll is None:
        click.echo("  No game assembly found among extracted files")
        return False

    click.echo(f"Decompiling {game_dll.name}...")
    decompiled_dir = game_src_dir / "Decompiled"

    # Primary: bundled decompile-helper (per-type, reliable on large assemblies)
    success = decompile_with_helper(
        game_dll, decompiled_dir,
        reference_dir=assemblies_dir,
        per_type_timeout=30,
        total_timeout=timeout,
    )

    # Fallback: ilspycmd (whole-assembly, may hang on large DLLs)
    if not success and is_ilspycmd_available():
        click.echo("  Retrying with ilspycmd...")
        if decompiled_dir.exists():
            shutil.rmtree(decompiled_dir)
        success = decompile_assembly(
            game_dll, decompiled_dir,
            reference_dir=assemblies_dir,
            as_project=False,
            timeout=timeout,
        )

    if not success:
        click.echo("  Decompilation failed — falling back to stub generation")
        if decompiled_dir.exists():
            shutil.rmtree(decompiled_dir)
        return False

    # Clean up extracted assemblies (no longer needed)
    if info.is_single_file_bundle:
        extract_dir = game_src_dir / ".extracted-assemblies"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)

    return True


def _check_eol_frameworks(engine_dir: Path) -> str | None:
    """Check if engine uses an EOL .NET target framework.

    Returns the EOL framework name (e.g. "net7.0") or None.
    """
    import re
    for csproj in engine_dir.rglob("*.csproj"):
        try:
            src = csproj.read_text(encoding="utf-8")
        except OSError:
            continue
        m = re.search(r"<TargetFramework>(net[67]\.0)</TargetFramework>", src)
        if m:
            return m.group(1)
    return None


def _patch_getasset(output_dir: Path) -> None:
    """Patch GetAsset to warn instead of throw on missing assets.

    Missing assets can occur in any recovery mode: stubs have incomplete types,
    decompiled projects may have fresh preferences with uninitialized GUIDs.
    Throwing propagates through ImGui draw code and causes native crashes.
    """
    gdm_path = output_dir / "murder/src/Murder/Data/GameDataManager.cs"
    if not gdm_path.exists():
        return
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
        click.echo("  Patched engine: GetAsset warns instead of throwing")


def _patch_engine(output_dir: Path) -> None:
    """Apply compatibility patches to the Murder engine for recovered projects.

    Patches GetAsset to log warnings instead of throwing when assets are
    missing. Recovered projects may have assets that fail to deserialize
    (due to game-specific types), so hard crashes on missing GUIDs would
    make the editor unusable.
    """
    # Patch JsonTypeConverter to return typeof(object) instead of throwing
    # when a type can't be resolved. This is the root cause of most
    # deserialization failures — game-specific types not in the project
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

    # Patch GameLogger.Error to not force the debug console open.
    # The console uses ImGui.SetWindowFocus() every frame when visible,
    # which steals focus from all other windows. Error spam from
    # rendering (invalid batches, missing components) makes the editor
    # unresponsive because the console keeps stealing focus.
    logger_path = output_dir / "murder/src/Murder/Diagnostics/GameLogger.cs"
    if logger_path.exists():
        logger_src = logger_path.read_text(encoding="utf-8")
        old_show = (
            "        OutputToLog(outputMessage, LogType.Error, new Vector4(1, 0.25f, 0.5f, 1));\n"
            "        _scrollToBottom = 2;\n"
            "        _showDebug = true;"
        )
        new_show = (
            "        OutputToLog(outputMessage, LogType.Error, new Vector4(1, 0.25f, 0.5f, 1));\n"
            "        _scrollToBottom = 2;"
        )
        if old_show in logger_src:
            logger_src = logger_src.replace(old_show, new_show)
            logger_path.write_text(logger_src, encoding="utf-8")
            click.echo("  Patched engine: Error logging no longer forces console open")


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
    skip_dirs = {"content", "assets"}  # Game data handled by split_assets
    skip_files = {"game_config", "game_config.json"}  # Handled separately with type remapping

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

    # Build speaker name lookup — matches any SpeakerAsset type
    speaker_names: dict[str, str] = {}
    for s in db.get_by_type_suffix("SpeakerAsset"):
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


def _use_decompiled_game_class(
    output_dir: Path, game_name: str, db: GameDatabase,
) -> None:
    """Replace scaffold game class with the decompiled one.

    The scaffold generates a minimal IMurderGame stub. With full decompilation,
    the real game class has CreateRenderContext, Profile casts,
    and other overrides the editor needs at runtime.
    """
    game_src_dir = output_dir / "src" / game_name
    decompiled_dir = game_src_dir / "Decompiled"

    # Find the decompiled IMurderGame implementation
    import re
    game_class = None
    game_ns = None
    game_class_file = None
    for cs_file in decompiled_dir.rglob("*.cs"):
        try:
            src = cs_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        # Look for `class X : IMurderGame` (the real game class, not the scaffold)
        m = re.search(r'class\s+(\w+)\s*:\s*IMurderGame', src)
        if m:
            game_class = m.group(1)
            ns_match = re.search(r'namespace\s+([\w.]+)', src)
            game_ns = ns_match.group(1) if ns_match else ""
            game_class_file = cs_file
            break

    if not game_class:
        return

    click.echo(f"  Using decompiled game class: {game_ns}.{game_class}")

    # Remove scaffold game class
    stub_game = game_src_dir / f"{game_name}Game.cs"
    if stub_game.exists():
        stub_game.unlink()

    # Rewire architect to extend decompiled game class
    editor_dir = output_dir / "src" / f"{game_name}.Editor"
    architect_path = editor_dir / f"{game_name}Architect.cs"
    if architect_path.exists():
        using = f"using {game_ns};\n" if game_ns else ""
        architect_path.write_text(
            f"{using}using Murder.Editor;\n\n"
            f"namespace {game_name}.Editor;\n\n"
            f"public class {game_name}Architect : {game_class}, IMurderArchitect\n"
            f"{{\n}}\n",
            encoding="utf-8",
        )

    # Update Program.cs to use the architect
    program_path = editor_dir / "Program.cs"
    if program_path.exists():
        program_path.write_text(
            f"using Murder.Editor;\n\n"
            f"namespace {game_name}.Editor;\n\n"
            f"public static class Program\n"
            f"{{\n"
            f"    [STAThread]\n"
            f"    static void Main()\n"
            f"    {{\n"
            f"        using var editor = new Architect(new {game_name}Architect());\n"
            f"        editor.Run();\n"
            f"    }}\n"
            f"}}\n",
            encoding="utf-8",
        )


def _remap_game_config_type(resources_dir: Path) -> None:
    """Remap game_config $type to Murder.Assets.GameProfile for stub mode.

    Stub mode doesn't have the game's custom GameProfile subclass, so we
    remap to the base class that the engine can deserialize.
    """
    config_path = resources_dir / "game_config"
    if not config_path.exists():
        return
    config = load_json(config_path)
    original_type = config.get("$type", "")
    if original_type and original_type != "Murder.Assets.GameProfile":
        config["$type"] = "Murder.Assets.GameProfile"
        save_json(config, config_path)


def _fix_init_from_build_errors(
    output_dir: Path, game_name: str,
) -> int:
    """Fix init→set in engine files by doing a trial build and parsing errors.

    Only modifies engine files that actually cause CS8852 errors from the
    decompiled code. This avoids unnecessary changes to engine files that
    the decompiled code never touches.

    Returns the number of engine files fixed.
    """
    import re
    import subprocess

    editor_dir = output_dir / "src" / f"{game_name}.Editor"
    engine_dir = output_dir / "murder"

    # Trial build — capture CS8852 errors
    click.echo("  Trial build to detect init→set targets...")
    result = subprocess.run(
        ["dotnet", "build", "--nologo", "-v", "quiet"],
        cwd=str(editor_dir),
        capture_output=True, text=True, timeout=300,
    )

    # Parse CS8852 errors to find affected property names
    # Format: "Init-only property or indexer 'TypeName.PropName' can only..."
    prop_pattern = re.compile(
        r"Init-only property or indexer '([^']+)'"
    )
    affected_props: set[str] = set()
    for line in result.stdout.splitlines() + result.stderr.splitlines():
        if "CS8852" in line:
            m = prop_pattern.search(line)
            if m:
                affected_props.add(m.group(1))

    if not affected_props:
        return 0

    # Map property names to type names (e.g. "AgentSpriteComponent.YSortOffset" → "AgentSpriteComponent")
    affected_types = {p.rsplit(".", 1)[0].split(".")[-1] for p in affected_props}
    click.echo(f"  Found {len(affected_types)} engine types needing init→set")

    # Find engine source files for these types and apply init→set
    init_pattern = re.compile(r'\binit\s*;')
    readonly_struct_pattern = re.compile(r'\breadonly\s+(record\s+)?struct\b')
    readonly_prop_pattern = re.compile(
        r'(\bpublic\s+)readonly(\s+.+?\s*\{[^}]*\bset\b)'
    )

    count = 0
    search_dirs = [engine_dir / "src"]
    for subdir in ("bang", "gum"):
        sub_src = engine_dir / subdir / "src"
        if sub_src.is_dir():
            search_dirs.append(sub_src)

    for src_dir in search_dirs:
        if not src_dir.is_dir():
            continue
        for cs_file in src_dir.rglob("*.cs"):
            # Only process files that define one of the affected types
            stem = cs_file.stem
            # Quick check: file name often matches type name
            if not any(t in stem or stem in t for t in affected_types):
                # Slower check: read file and look for type declarations
                try:
                    src = cs_file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                if not any(
                    re.search(rf'\b(class|struct|record)\s+{re.escape(t)}\b', src)
                    for t in affected_types
                ):
                    continue
            else:
                try:
                    src = cs_file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue

            if not init_pattern.search(src):
                continue

            new_src = init_pattern.sub("set;", src)
            new_src = readonly_struct_pattern.sub(
                lambda m: f"{'record ' if m.group(1) else ''}struct", new_src,
            )
            new_src = readonly_prop_pattern.sub(r'\1\2', new_src)

            if new_src != src:
                cs_file.write_text(new_src, encoding="utf-8")
                count += 1

    # Suppress BANG analyzer errors for the affected files
    if count > 0:
        _suppress_init_warnings(engine_dir)

    return count


def _suppress_init_warnings(engine_dir: Path) -> None:
    """Add <NoWarn> for init→set side effects to the engine Directory.Build.props.

    Changing init→set on readonly structs triggers unsuppressable CS8341/CS8659.
    Removing readonly triggers BANG analyzer errors (BANG0002/3002/5002).
    These are all compile-time-only constraints with no runtime impact.
    """
    dbp = engine_dir / "Directory.Build.props"
    if not dbp.exists():
        return
    src = dbp.read_text(encoding="utf-8")
    if "BANG0002" in src:
        return  # already patched
    src = src.replace(
        "</PropertyGroup>",
        "  <NoWarn>$(NoWarn);BANG0002;BANG3002;BANG5002</NoWarn>\n  </PropertyGroup>",
        1,
    )
    dbp.write_text(src, encoding="utf-8")


def _csv_escape(value: str) -> str:
    """Escape a value for CSV output."""
    if not value:
        return ""
    if "," in value or '"' in value or "\n" in value:
        return '"' + value.replace('"', '""') + '"'
    return value


# Known third-party namespaces → NuGet package names.
# Extend this map as more Murder Engine games are recovered.
_USING_TO_NUGET: dict[str, str] = {
    "using Steamworks;": "Steamworks.NET",
}


def _add_nuget_packages(game_src_dir: Path, game_name: str) -> list[str]:
    """Scan decompiled source for third-party using directives and add NuGet refs.

    Returns list of package names that were added.
    """
    decompiled_dir = game_src_dir / "Decompiled"
    if not decompiled_dir.is_dir():
        return []

    # Scan all .cs files for known third-party usings
    needed: set[str] = set()
    for cs_file in decompiled_dir.rglob("*.cs"):
        try:
            src = cs_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for using_stmt, package in _USING_TO_NUGET.items():
            if using_stmt in src:
                needed.add(package)

    if not needed:
        return []

    # Insert PackageReference items into the .csproj
    csproj_path = game_src_dir / f"{game_name}.csproj"
    if not csproj_path.exists():
        return []

    csproj = csproj_path.read_text(encoding="utf-8")

    pkg_lines = "\n".join(
        f'    <PackageReference Include="{pkg}" Version="*" />'
        for pkg in sorted(needed)
    )
    pkg_group = f"\n  <ItemGroup>\n{pkg_lines}\n  </ItemGroup>\n"

    # Insert before the closing </Project>
    csproj = csproj.replace("</Project>", f"{pkg_group}</Project>")
    csproj_path.write_text(csproj, encoding="utf-8")

    return sorted(needed)
