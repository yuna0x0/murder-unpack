"""Handle native library compatibility for platforms not covered by Murder.FNA.

Murder.FNA NuGet package (26.x) ships native libraries for win-x64,
win-x86, linux-x64, linux-arm64, and osx — but NOT win-arm64.
FNA's fnalibs (SDL3, FAudio, FNA3D, libtheorafile) also don't include
ARM64 Windows builds.

On Windows ARM64, the fix is to build and run as x64 — Windows ARM64
runs x64 apps through its built-in emulation layer. This requires the
x64 .NET runtime to be installed alongside the ARM64 one.
"""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path

import click


def is_arm64_windows() -> bool:
    """Detect if we're running on Windows ARM64."""
    if platform.system() != "Windows":
        return False
    machine = platform.machine().lower()
    return machine in ("arm64", "aarch64")


def has_x64_dotnet_runtime(major_version: int = 8) -> bool:
    """Check if x64 .NET runtime is installed on ARM64 Windows.

    On ARM64 Windows, x64 .NET installs to C:\\Program Files\\dotnet\\x64\\
    or can be found via `dotnet --list-runtimes` with x64 architecture.
    """
    # Check the standard x64 dotnet location on ARM64 Windows
    x64_dotnet = Path(r"C:\Program Files\dotnet\x64\dotnet.exe")
    if x64_dotnet.exists():
        try:
            result = subprocess.run(
                [str(x64_dotnet), "--list-runtimes"],
                capture_output=True, text=True, timeout=10,
            )
            if f"Microsoft.NETCore.App {major_version}." in result.stdout:
                return True
        except (subprocess.SubprocessError, OSError):
            pass

    return False


def setup_arm64_workaround(project_dir: Path) -> None:
    """Set up x64 build workaround for ARM64 Windows.

    Generates:
    - Directory.Build.props with conditional RuntimeIdentifier for ARM64
    - A run.cmd launch script that uses x64 dotnet
    """
    _generate_directory_build_props(project_dir)
    _generate_launch_script(project_dir)


def check_arm64_readiness(project_dir: Path) -> bool:
    """Check if the project is ready to run on ARM64 Windows.

    Returns True if x64 .NET runtime is available.
    Prints instructions if not.
    """
    # Detect game name from src/ directory
    game_name = _detect_game_name(project_dir)

    if has_x64_dotnet_runtime():
        click.echo("  x64 .NET runtime found -- project will build and run via x64 emulation")
        return True

    click.echo(
        "\n  WARNING: x64 .NET 8.0 runtime is required but not installed.\n"
        "  Murder Engine's native libraries (SDL3, FAudio, FNA3D) don't support\n"
        "  ARM64 Windows. The project must build and run as x64 under emulation.\n"
        "\n"
        "  Install x64 .NET 8.0 runtime:\n"
        "    winget install Microsoft.DotNet.Runtime.8 --architecture x64\n"
        "\n"
        "  Or download from:\n"
        "    https://dotnet.microsoft.com/download/dotnet/8.0\n"
        "    (Select Windows > x64 > Runtime)\n"
        "\n"
        "  After installing, build and run with:\n"
        f"    cd {project_dir}\n"
        f"    dotnet build src\\{game_name}.Editor\\{game_name}.Editor.csproj -r win-x64\n"
        f"    src\\{game_name}.Editor\\bin\\Debug\\net8.0\\win-x64\\{game_name}.Editor.exe\n"
    )
    return False


def _detect_game_name(project_dir: Path) -> str:
    """Detect game name from the project's src/ directory."""
    src_dir = project_dir / "src"
    if src_dir.exists():
        for d in src_dir.iterdir():
            if d.is_dir() and d.name.endswith(".Editor"):
                return d.name.removesuffix(".Editor")
    return "RecoveredGame"


def _generate_directory_build_props(project_dir: Path) -> None:
    """Generate Directory.Build.props that forces win-x64 on ARM64 Windows.

    MSBuild evaluates the OS architecture at build time. On ARM64 Windows,
    this sets RuntimeIdentifier to win-x64, which:
    - Copies x64 native libraries from NuGet to the output
    - Generates an x64 apphost (.exe) that runs under emulation
    - The x64 .NET runtime loads the x64 native DLLs correctly
    """
    props_path = project_dir / "Directory.Build.props"

    # If there's already a Directory.Build.props, merge carefully
    if props_path.exists():
        existing = props_path.read_text(encoding="utf-8")
        if "RuntimeIdentifier" in existing:
            return  # Already configured
        if "win-x64" in existing:
            return  # Already has x64 config

    content = """\
<Project>
  <!--
    ARM64 Windows workaround: Murder.FNA does not ship ARM64 native
    libraries (SDL3, FAudio, FNA3D, libtheorafile). Force x64 build
    so the x64 natives are used under Windows ARM64 emulation.
    Requires x64 .NET runtime installed alongside ARM64.
  -->
  <PropertyGroup Condition="$([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture) == 'Arm64' And $([MSBuild]::IsOSPlatform('Windows'))">
    <RuntimeIdentifier>win-x64</RuntimeIdentifier>
  </PropertyGroup>
</Project>
"""
    props_path.write_text(content, encoding="utf-8")


def _generate_launch_script(project_dir: Path) -> None:
    """Generate a Windows batch script that launches the editor correctly.

    On ARM64 Windows, uses the x64 dotnet or runs the x64 exe directly.
    On x64 Windows, uses regular dotnet run.
    """
    # Detect game name from src/ directory
    src_dir = project_dir / "src"
    game_name = "RecoveredGame"
    if src_dir.exists():
        for d in src_dir.iterdir():
            if d.is_dir() and d.name.endswith(".Editor"):
                game_name = d.name.removesuffix(".Editor")
                break

    script_path = project_dir / "run-editor.cmd"
    content = f"""\
@echo off
REM Launch the Murder Engine editor
REM On ARM64 Windows, builds and runs as x64 under emulation

set EDITOR_DIR=%~dp0src\\{game_name}.Editor
set EDITOR_CSPROJ=%EDITOR_DIR%\\{game_name}.Editor.csproj

REM Check architecture
for /f "tokens=*" %%a in ('powershell -NoProfile -Command "[System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture"') do set ARCH=%%a

if /i "%ARCH%"=="Arm64" (
    echo Building for x64 ^(ARM64 Windows detected^)...
    dotnet build "%EDITOR_CSPROJ%" -r win-x64 --no-self-contained
    if errorlevel 1 (
        echo Build failed. Ensure x64 .NET 8.0 runtime is installed:
        echo   winget install Microsoft.DotNet.Runtime.8 --architecture x64
        exit /b 1
    )
    echo Starting editor...
    start "" "%EDITOR_DIR%\\bin\\Debug\\net8.0\\win-x64\\{game_name}.Editor.exe"
) else (
    echo Building editor...
    dotnet build "%EDITOR_CSPROJ%"
    if errorlevel 1 exit /b 1
    echo Starting editor...
    start "" "%EDITOR_DIR%\\bin\\Debug\\net8.0\\{game_name}.Editor.exe"
)
"""
    script_path.write_text(content, encoding="utf-8")
