"""Auto-detect .NET deployment format from game executables.

Supports Windows (PE), Linux (ELF), and macOS (Mach-O) binaries.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from murder_unpack.binary.bundle_extractor import BUNDLE_SIGNATURE


class ExeFormat(Enum):
    PE = "PE"          # Windows .exe
    ELF = "ELF"        # Linux
    MACHO = "Mach-O"   # macOS
    UNKNOWN = "Unknown"


class DeploymentType(Enum):
    NATIVE_AOT = "NativeAOT"
    SINGLE_FILE = "SingleFileBundle"
    SELF_CONTAINED = "SelfContained"
    FRAMEWORK_DEPENDENT = "FrameworkDependent"
    UNKNOWN = "Unknown"


class Platform(Enum):
    WINDOWS = "Windows"
    LINUX = "Linux"
    MACOS = "macOS"
    UNKNOWN = "Unknown"


@dataclass
class BinaryInfo:
    path: Path
    exe_format: ExeFormat
    deployment: DeploymentType
    platform: Platform
    has_clr: bool = False
    is_native_aot: bool = False
    is_single_file_bundle: bool = False
    has_managed_assemblies: bool = False
    bundle_offset: int | None = None
    bundle_file_count: int | None = None


NATIVEAOT_MARKERS = [b"NativeAOT compilation", b"RhpNewFast", b"DotNetRuntimeDebugHeader"]


def detect_exe_format(data: bytes) -> tuple[ExeFormat, Platform]:
    """Detect executable format from magic bytes."""
    if data[:2] == b"MZ":
        return ExeFormat.PE, Platform.WINDOWS
    if data[:4] == b"\x7fELF":
        return ExeFormat.ELF, Platform.LINUX
    # Mach-O: 64-bit
    if data[:4] in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf"):
        return ExeFormat.MACHO, Platform.MACOS
    # Mach-O: FAT/universal
    if data[:4] in (b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"):
        return ExeFormat.MACHO, Platform.MACOS
    return ExeFormat.UNKNOWN, Platform.UNKNOWN


def _check_pe_clr(data: bytes) -> bool:
    """Check if a PE file has a CLR data directory (managed .NET)."""
    if data[:2] != b"MZ":
        return False
    try:
        pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe_offset:pe_offset + 4] != b"PE\x00\x00":
            return False
        # COFF header is at pe_offset + 4
        optional_hdr_offset = pe_offset + 4 + 20
        magic = struct.unpack_from("<H", data, optional_hdr_offset)[0]
        # PE32+ (64-bit): magic = 0x20b, data directories start at offset 112
        # PE32 (32-bit): magic = 0x10b, data directories start at offset 96
        if magic == 0x20b:
            dd_offset = optional_hdr_offset + 112
        elif magic == 0x10b:
            dd_offset = optional_hdr_offset + 96
        else:
            return False
        # CLR Runtime Header is data directory index 14
        clr_rva = struct.unpack_from("<I", data, dd_offset + 14 * 8)[0]
        return clr_rva != 0
    except (struct.error, IndexError):
        return False


def _find_bundle_signature(data: bytes) -> int | None:
    """Find .NET single-file bundle signature in binary data."""
    pos = data.find(BUNDLE_SIGNATURE)
    if pos == -1:
        return None
    return pos


def _check_nativeaot(data: bytes) -> bool:
    """Check for NativeAOT compilation markers."""
    return any(marker in data for marker in NATIVEAOT_MARKERS)


def _check_runtime_lib(exe_path: Path, platform: Platform) -> bool:
    """Check if a .NET runtime library exists alongside the executable."""
    parent = exe_path.parent
    runtime_libs = {
        Platform.WINDOWS: "coreclr.dll",
        Platform.LINUX: "libcoreclr.so",
        Platform.MACOS: "libcoreclr.dylib",
    }
    lib_name = runtime_libs.get(platform)
    if lib_name:
        return (parent / lib_name).exists()
    return False


def _check_runtimeconfig(exe_path: Path) -> bool:
    """Check for .runtimeconfig.json alongside executable."""
    stem = exe_path.stem
    return (exe_path.parent / f"{stem}.runtimeconfig.json").exists()


def detect_binary(path: Path | str) -> BinaryInfo:
    """Detect .NET deployment format of a game executable.

    Works with Windows PE (.exe), Linux ELF, and macOS Mach-O binaries.

    Detection logic:
    - Single-file bundles are identified by the bundle signature and parsed
      to check whether they contain managed assemblies (FileType.ASSEMBLY).
    - NativeAOT markers (RhpNewFast, etc.) can false-positive when the
      bundled coreclr.dll contains those strings. A single-file bundle
      with managed assemblies is NOT NativeAOT — the managed IL is intact.
    - True NativeAOT binaries have no managed assemblies in the bundle
      (or no bundle at all).
    """
    from murder_unpack.binary.bundle_extractor import FileType, parse_bundle

    path = Path(path)
    data = path.read_bytes()

    exe_format, platform = detect_exe_format(data)

    info = BinaryInfo(
        path=path,
        exe_format=exe_format,
        deployment=DeploymentType.UNKNOWN,
        platform=platform,
    )

    # Check for CLR header (PE only)
    if exe_format == ExeFormat.PE:
        info.has_clr = _check_pe_clr(data)

    # Check for single-file bundle (any platform — format is appended
    # identically to PE, ELF, and Mach-O host executables)
    manifest = parse_bundle(data)
    if manifest is not None:
        info.is_single_file_bundle = True
        info.bundle_file_count = len(manifest.entries)
        info.bundle_offset = manifest.entries[0].offset if manifest.entries else None
        info.has_managed_assemblies = any(
            e.file_type == FileType.ASSEMBLY for e in manifest.entries
        )

    # NativeAOT detection: string markers in the binary, but ONLY trust
    # them if the bundle does NOT contain managed assemblies. A managed
    # single-file bundle embeds coreclr which contains these same strings.
    has_aot_markers = _check_nativeaot(data)
    if has_aot_markers and not info.has_managed_assemblies:
        info.is_native_aot = True

    # Determine primary deployment type
    if info.is_native_aot:
        info.deployment = DeploymentType.NATIVE_AOT
    elif info.is_single_file_bundle:
        info.deployment = DeploymentType.SINGLE_FILE
    elif _check_runtime_lib(path, platform):
        info.deployment = DeploymentType.SELF_CONTAINED
    elif _check_runtimeconfig(path):
        info.deployment = DeploymentType.FRAMEWORK_DEPENDENT
    elif info.has_clr:
        info.deployment = DeploymentType.FRAMEWORK_DEPENDENT

    return info
