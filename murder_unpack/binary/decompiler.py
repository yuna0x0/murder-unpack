"""Decompile .NET assemblies to C# source.

Primary: bundled decompile-helper (ICSharpCode.Decompiler, per-type with timeouts).
Fallback: ilspycmd global tool (whole-assembly, may hang on large DLLs).

Requires: dotnet SDK (for building/running the helper).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
from io import TextIOWrapper
from pathlib import Path

import click

# Path to the C# decompile-helper project shipped with murder-unpack
_HELPER_DIR = Path(__file__).parent / "decompile-helper"


# ─── Post-processing ─────────────────────────────────────────────────────────

# Compiler-generated single-element list wrapper. ILSpy emits this as
# `new global::<>z__ReadOnlySingleElementList<T>(value)` which is not valid C#.
# Replace with `new[] { value }` which is the idiomatic equivalent.
_RE_READONLY_SINGLE = re.compile(
    r"new\s+global::<>z__ReadOnlySingleElementList<[^>]+>\(([^)]+)\)"
)


def _postprocess_decompiled(output_dir: Path) -> int:
    """Fix known ICSharpCode.Decompiler artifacts in decompiled .cs files.

    Returns the number of files fixed.
    """
    fixes = 0

    # Murder.Serializer output: {GameName}SerializerOptionsExtensions
    # The generator produces this for every project that references it.
    for cs_file in output_dir.rglob("*SerializerOptionsExtensions.cs"):
        cs_file.unlink()
        fixes += 1

    # Note: Bang/ directory (source-generator output) is handled by
    # recovery based on engine version -- see _cleanup_generated_code().

    # Fix decompiler artifacts in .cs files:
    # - `readonly struct` with `set` properties → `struct` (CS8341)
    #   InitAccessors=false emits `set` which is invalid on readonly struct
    # - Compiler-generated type references (e.g. <>z__ReadOnlySingleElementList)
    _re_readonly_struct = re.compile(r'\breadonly\s+(record\s+)?struct\b')
    for cs_file in output_dir.rglob("*.cs"):
        try:
            src = cs_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        new_src = src
        # Remove `readonly` from struct declarations that have `set` properties
        if _re_readonly_struct.search(new_src) and re.search(r'\bset\b', new_src):
            new_src = _re_readonly_struct.sub(
                lambda m: f"{'record ' if m.group(1) else ''}struct", new_src,
            )
        new_src = _RE_READONLY_SINGLE.sub(r"new[] { \1 }", new_src)

        # Add missing using directives for common unqualified types.
        # The decompiler sometimes emits Vector2/Vector3 without a using.
        # Multiple namespaces provide Vector types depending on engine version:
        #   System.Numerics (newer Murder), Murder.Core.Geometry (older Murder),
        #   Microsoft.Xna.Framework (FNA/MonoGame games).
        # Only add System.Numerics if no other Vector provider is already imported.
        if (re.search(r'\bVector[234]\b', new_src)
                and "using System.Numerics;" not in new_src
                and "using Murder.Core.Geometry;" not in new_src
                and "using Microsoft.Xna.Framework;" not in new_src):
            last_using = -1
            for m in re.finditer(r'^using [^;]+;\s*$', new_src, re.MULTILINE):
                last_using = m.end()
            if last_using >= 0:
                new_src = new_src[:last_using] + "using System.Numerics;\n" + new_src[last_using:]
            else:
                new_src = "using System.Numerics;\n\n" + new_src

        # Promote internal types to public. The decompiler emits internal
        # for types that were internal in the original assembly, but Murder's
        # source generators (Bang.Generator, Murder.Serializer) need them
        # to be public to generate correct code.
        new_src = re.sub(
            r'^(internal\s+)((?:readonly\s+)?(?:struct|class|record|enum)\b)',
            r'public \2',
            new_src,
            flags=re.MULTILINE,
        )

        if new_src != src:
            cs_file.write_text(new_src, encoding="utf-8")
            fixes += 1

    return fixes


# ─── Helper-based decompilation (preferred) ─────────────────────────────────


def is_dotnet_available() -> bool:
    """Check if the dotnet SDK is available."""
    return shutil.which("dotnet") is not None


def _build_helper() -> Path | None:
    """Build the decompile-helper project, return path to the built DLL.

    Returns None if the build fails.
    """
    if not _HELPER_DIR.exists():
        return None

    try:
        result = subprocess.run(
            ["dotnet", "build", "-c", "Release", "--nologo", "-v", "quiet"],
            cwd=str(_HELPER_DIR),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            click.echo(f"  decompile-helper build failed:\n{result.stderr}", err=True)
            return None

        dll = _HELPER_DIR / "bin" / "Release" / "net8.0" / "decompile-helper.dll"
        return dll if dll.exists() else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def decompile_with_helper(
    assembly_path: Path | str,
    output_dir: Path | str,
    reference_dir: Path | str | None = None,
    namespace_filter: str | None = None,
    per_type_timeout: int = 30,
    total_timeout: int = 600,
) -> bool:
    """Decompile a .NET assembly using the bundled decompile-helper.

    Decompiles each type individually with per-type timeouts, avoiding
    the hang that ilspycmd suffers on large assemblies.

    Args:
        assembly_path: Path to the .dll to decompile
        output_dir: Output directory for decompiled .cs files
        reference_dir: Directory containing reference assemblies
        namespace_filter: Only decompile types in this namespace
        per_type_timeout: Timeout per type in seconds (default: 30)
        total_timeout: Total timeout for the entire process (default: 600)

    Returns:
        True if decompilation succeeded
    """
    assembly_path = Path(assembly_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build the helper
    click.echo("  Building decompile-helper...")
    helper_dll = _build_helper()
    if helper_dll is None:
        click.echo("  Failed to build decompile-helper")
        return False

    # Run the helper
    cmd = [
        "dotnet", str(helper_dll),
        str(assembly_path), str(output_dir),
        "--timeout", str(per_type_timeout),
    ]
    if reference_dir is not None:
        cmd.extend(["--refs", str(reference_dir)])
    if namespace_filter is not None:
        cmd.extend(["--namespace", namespace_filter])

    click.echo(f"  Decompiling {assembly_path.name} → {output_dir}")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        succeeded = 0
        failed = 0
        total = 0

        # Parse JSON progress lines from stdout
        for line in iter(proc.stdout.readline, ""):
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                status = msg.get("status", "")
                message = msg.get("message", "")

                if status == "start":
                    click.echo(f"  {message}")
                elif status == "ok":
                    succeeded += 1
                    # Print progress every 100 types
                    if succeeded % 100 == 0:
                        click.echo(f"  ... {succeeded} types decompiled")
                elif status == "timeout":
                    failed += 1
                    click.echo(f"  Timeout: {message}")
                elif status == "error":
                    failed += 1
                    click.echo(f"  Error: {message}")
                elif status == "done":
                    click.echo(f"  {message}")
            except json.JSONDecodeError:
                pass

        proc.stdout.close()
        returncode = proc.wait(timeout=total_timeout)
        proc.stderr.close()

        if returncode == 0:
            cs_files = list(output_dir.rglob("*.cs"))
            click.echo(f"  Decompilation complete: {len(cs_files)} .cs files")
            fixes = _postprocess_decompiled(output_dir)
            if fixes:
                click.echo(f"  Post-processing: fixed {fixes} decompiler artifacts")
        else:
            click.echo(f"  decompile-helper exited with code {returncode}")

        return returncode == 0

    except subprocess.TimeoutExpired:
        click.echo(f"  decompile-helper timed out after {total_timeout}s — killing")
        proc.kill()
        proc.wait()
        return False
    except FileNotFoundError:
        click.echo("  dotnet not found")
        return False


# ─── ilspycmd fallback ───────────────────────────────────────────────────────


def is_ilspycmd_available() -> bool:
    """Check if ilspycmd is installed and available."""
    return shutil.which("ilspycmd") is not None


def _stream_output(pipe: TextIOWrapper, prefix: str) -> None:
    """Stream subprocess output lines to stderr for live progress."""
    for line in iter(pipe.readline, ""):
        line = line.rstrip()
        if line:
            click.echo(f"  [ilspycmd] {line}", err=True)
    pipe.close()


def decompile_assembly(
    assembly_path: Path | str,
    output_dir: Path | str,
    reference_dir: Path | str | None = None,
    as_project: bool = True,
    timeout: int = 600,
) -> bool:
    """Decompile a .NET assembly to C# source using ilspycmd.

    Args:
        assembly_path: Path to the .dll to decompile
        output_dir: Output directory for decompiled source
        reference_dir: Directory containing reference assemblies
        as_project: If True, generate a compilable project (-p flag)
        timeout: Timeout in seconds for ilspycmd (default: 600)

    Returns:
        True if decompilation succeeded
    """
    assembly_path = Path(assembly_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = ["ilspycmd", "--disable-updatecheck"]
    if reference_dir is not None:
        cmd.extend(["-r", str(reference_dir)])
    if as_project:
        cmd.extend(["-p", "--nested-directories"])
    cmd.extend(["-o", str(output_dir), str(assembly_path)])

    click.echo(f"  Running: {' '.join(cmd)}")
    click.echo(f"  Decompiling {assembly_path.name} → {output_dir}")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Stream stdout and stderr in background threads so user sees progress
        stdout_thread = threading.Thread(
            target=_stream_output, args=(proc.stdout, "stdout"), daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_stream_output, args=(proc.stderr, "stderr"), daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        returncode = proc.wait(timeout=timeout)
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)

        if returncode == 0:
            # Count decompiled files
            cs_files = list(output_dir.rglob("*.cs"))
            click.echo(f"  Decompilation complete: {len(cs_files)} .cs files")
        else:
            click.echo(f"  ilspycmd exited with code {returncode}")

        return returncode == 0
    except subprocess.TimeoutExpired:
        click.echo(f"  ilspycmd timed out after {timeout}s — killing process")
        proc.kill()
        proc.wait()
        return False
    except FileNotFoundError:
        click.echo("  ilspycmd not found")
        return False


def find_game_assembly(assemblies_dir: Path | str) -> Path | None:
    """Find the game assembly among extracted .dll files.

    Looks for assemblies that are NOT System.*, Microsoft.*, or known framework dlls.
    """
    assemblies_dir = Path(assemblies_dir)
    skip_prefixes = (
        "System.", "Microsoft.", "FNA", "MonoGame.", "SDL", "FAudio",
        "Newtonsoft.", "Bang.", "Murder.", "Gum.",
    )

    candidates: list[Path] = []
    for dll in assemblies_dir.glob("*.dll"):
        if not any(dll.stem.startswith(p.rstrip(".")) for p in skip_prefixes):
            candidates.append(dll)

    if not candidates:
        return None

    # Return the largest non-framework DLL (likely the game)
    return max(candidates, key=lambda p: p.stat().st_size)
