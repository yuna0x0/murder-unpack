"""Auto-detect .NET deployment format from game executables.

Supports Windows (PE), Linux (ELF), and macOS (Mach-O) binaries.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


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
    bundle_offset: int | None = None
    bundle_file_count: int | None = None


# .NET single-file bundle signature: SHA-256 of ".net core bundle"
BUNDLE_SIGNATURE = bytes([
    0x8b, 0x12, 0x02, 0xb9, 0x6a, 0x61, 0x20, 0x38,
    0x72, 0x7b, 0x93, 0x02, 0x14, 0xd7, 0xa0, 0x32,
    0x13, 0xf5, 0xb9, 0xe6, 0xef, 0xae, 0x33, 0x18,
    0xee, 0x3b, 0x2d, 0xce, 0x24, 0xb3, 0x6a, 0xae,
])

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
    A binary can be both NativeAOT AND a single-file bundle (NativeAOT
    published as single-file), so both flags are set independently.
    The primary deployment type reflects the most specific classification.
    """
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

    # Check for NativeAOT markers (independent flag)
    info.is_native_aot = _check_nativeaot(data)

    # Check for single-file bundle (independent flag, any platform)
    sig_pos = _find_bundle_signature(data)
    if sig_pos is not None:
        try:
            manifest_offset = struct.unpack_from("<Q", data, sig_pos - 8)[0]
            if 0 < manifest_offset < len(data):
                info.is_single_file_bundle = True
                info.bundle_offset = manifest_offset
                pos = manifest_offset
                _major = struct.unpack_from("<I", data, pos)[0]
                _minor = struct.unpack_from("<I", data, pos + 4)[0]
                file_count = struct.unpack_from("<I", data, pos + 8)[0]
                info.bundle_file_count = file_count
        except (struct.error, IndexError):
            pass

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
