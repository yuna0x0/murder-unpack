"""Extract .NET assemblies from single-file bundles.

Pure Python implementation — works on PE (.exe), ELF, and Mach-O binaries.
The bundle format is platform-agnostic (appended after the native executable).

Bundle format (v6+, .NET 6/7/8):
  - Manifest header at offset stored 8 bytes before the bundle signature
  - Header: major(u32), minor(u32), file_count(i32), bundleId(7bit-len string)
  - v2+: depsJsonOffset(i64), depsJsonSize(i64), runtimeConfigOffset(i64),
          runtimeConfigSize(i64), flags(u64)
  - File entries: offset(i64), size(i64), compressedSize(i64, v6+), type(u8),
                  relativePath(7bit-len string)
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path


class FileType(IntEnum):
    UNKNOWN = 0
    ASSEMBLY = 1
    NATIVE_BINARY = 2
    DEPS_JSON = 3
    RUNTIME_CONFIG_JSON = 4
    SYMBOLS = 5


@dataclass
class BundleEntry:
    offset: int
    size: int
    compressed_size: int
    file_type: FileType
    relative_path: str


@dataclass
class BundleManifest:
    major_version: int
    minor_version: int
    entries: list[BundleEntry]
    bundle_id: str


# .NET single-file bundle signature: SHA-256 of ".net core bundle"
BUNDLE_SIGNATURE = bytes([
    0x8b, 0x12, 0x02, 0xb9, 0x6a, 0x61, 0x20, 0x38,
    0x72, 0x7b, 0x93, 0x02, 0x14, 0xd7, 0xa0, 0x32,
    0x13, 0xf5, 0xb9, 0xe6, 0xef, 0xae, 0x33, 0x18,
    0xee, 0x3b, 0x2d, 0xce, 0x24, 0xb3, 0x6a, 0xae,
])


def _read_7bit_encoded_string(data: bytes, pos: int) -> tuple[str, int]:
    """Read a 7-bit encoded length-prefixed UTF-8 string."""
    length = 0
    shift = 0
    while True:
        b = data[pos]
        pos += 1
        length |= (b & 0x7F) << shift
        shift += 7
        if (b & 0x80) == 0:
            break
    end = pos + length
    if end > len(data):
        raise ValueError(f"String at offset {pos} extends past end of data ({end} > {len(data)})")
    s = data[pos:end].decode("utf-8")
    return s, end


def parse_bundle(data: bytes) -> BundleManifest | None:
    """Parse a .NET single-file bundle from raw binary data.

    Returns None if no bundle signature found.
    """
    sig_pos = data.find(BUNDLE_SIGNATURE)
    if sig_pos == -1:
        return None

    # Read manifest header offset (8 bytes before signature)
    if sig_pos < 8:
        return None
    manifest_offset = struct.unpack_from("<Q", data, sig_pos - 8)[0]
    if manifest_offset == 0 or manifest_offset >= len(data):
        return None

    pos = manifest_offset
    major = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    minor = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    file_count = struct.unpack_from("<i", data, pos)[0]
    pos += 4

    bundle_id, pos = _read_7bit_encoded_string(data, pos)

    # v2+ has extra header fields
    if major >= 2:
        pos += 8 * 4 + 8  # depsJson offset/size, runtimeConfig offset/size, flags

    entries: list[BundleEntry] = []
    for _ in range(file_count):
        offset = struct.unpack_from("<q", data, pos)[0]
        pos += 8
        size = struct.unpack_from("<q", data, pos)[0]
        pos += 8

        compressed_size = 0
        if major >= 6:
            compressed_size = struct.unpack_from("<q", data, pos)[0]
            pos += 8

        file_type = FileType(data[pos])
        pos += 1

        relative_path, pos = _read_7bit_encoded_string(data, pos)

        entries.append(BundleEntry(
            offset=offset,
            size=size,
            compressed_size=compressed_size,
            file_type=file_type,
            relative_path=relative_path,
        ))

    return BundleManifest(
        major_version=major,
        minor_version=minor,
        entries=entries,
        bundle_id=bundle_id,
    )


def extract_bundle(path: Path | str, output_dir: Path | str) -> list[Path]:
    """Extract all files from a .NET single-file bundle.

    Returns list of extracted file paths.
    """
    path = Path(path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    data = path.read_bytes()
    manifest = parse_bundle(data)
    if manifest is None:
        raise ValueError(f"No .NET single-file bundle found in {path}")

    extracted: list[Path] = []
    for entry in manifest.entries:
        out_path = output_dir / entry.relative_path
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if entry.compressed_size > 0:
            # v6+ deflate compression (raw deflate, no zlib header)
            compressed = data[entry.offset:entry.offset + entry.compressed_size]
            decompressor = zlib.decompressobj(-15)
            decompressed = decompressor.decompress(compressed)
            decompressed += decompressor.flush()
            out_path.write_bytes(decompressed)
        else:
            raw = data[entry.offset:entry.offset + entry.size]
            out_path.write_bytes(raw)

        extracted.append(out_path)

    return extracted


def list_bundle_contents(path: Path | str) -> BundleManifest | None:
    """List contents of a .NET single-file bundle without extracting."""
    data = Path(path).read_bytes()
    return parse_bundle(data)
