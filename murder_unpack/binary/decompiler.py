"""Invoke ILSpy command-line tool for full C# source recovery.

Requires: dotnet tool install -g ilspycmd
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


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


def decompile_assembly(
    assembly_path: Path | str,
    output_dir: Path | str,
    as_project: bool = True,
) -> bool:
    """Decompile a .NET assembly to C# source using ilspycmd.

    Args:
        assembly_path: Path to the .dll to decompile
        output_dir: Output directory for decompiled source
        as_project: If True, generate a compilable project (-p flag)

    Returns:
        True if decompilation succeeded
    """
    assembly_path = Path(assembly_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = ["ilspycmd"]
    if as_project:
        cmd.extend(["-p", "--nested-directories"])
    cmd.extend(["-o", str(output_dir), str(assembly_path)])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
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
