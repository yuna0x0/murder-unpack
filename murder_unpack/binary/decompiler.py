"""Invoke ILSpy command-line tool for full C# source recovery.

Requires: dotnet tool install -g ilspycmd
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from io import TextIOWrapper
from pathlib import Path

import click


def is_ilspycmd_available() -> bool:
    """Check if ilspycmd is installed and available."""
    return shutil.which("ilspycmd") is not None


def check_dotnet_tool() -> bool:
    """Check if ilspycmd is installed as a dotnet global tool."""
    try:
        result = subprocess.run(
            ["dotnet", "tool", "list", "-g"],
            capture_output=True, text=True, timeout=10,
        )
        return "ilspycmd" in result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


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
        "System.", "Microsoft.", "FNA", "SDL", "FAudio",
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
