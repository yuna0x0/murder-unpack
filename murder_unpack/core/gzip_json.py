"""GZip + JSON compression/decompression mirroring Murder's FileManager."""

from __future__ import annotations

import gzip
import json
import zlib
from pathlib import Path
from typing import Any


def decompress_gz_json(path: Path | str) -> dict[str, Any]:
    """Decompress a .gz file and parse as JSON.

    Mirrors FileManager.UnpackContent<T>() — GZipStream(Decompress) → JSON.
    Murder's .gz files may have trailing garbage after the JSON payload,
    so we decompress only the first gzip member.
    """
    path = Path(path)
    with open(path, "rb") as f:
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)  # gzip format
        compressed = f.read()
        raw = decompressor.decompress(compressed)
    return json.loads(raw)


def compress_json_gz(data: Any, path: Path | str) -> None:
    """Serialize to JSON and compress with gzip.

    Mirrors FileManager.PackContent<T>() — JSON → GZipStream(Compress).
    Uses indent=2 and CRLF line endings to match Murder's output.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    json_str = json.dumps(data, indent=2, ensure_ascii=False)
    # Murder uses CRLF line endings (Windows-style)
    json_bytes = json_str.replace("\n", "\r\n").encode("utf-8")
    with gzip.open(path, "wb") as f:
        f.write(json_bytes)


def decompress_gz_bytes(path: Path | str) -> bytes:
    """Decompress a .gz file and return raw bytes (for QOI images etc.)."""
    path = Path(path)
    with open(path, "rb") as f:
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        return decompressor.decompress(f.read())


def compress_bytes_gz(data: bytes, path: Path | str) -> None:
    """Compress raw bytes with gzip."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as f:
        f.write(data)


def save_json(data: Any, path: Path | str) -> None:
    """Save JSON to a file with Murder-compatible formatting."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    json_str = json.dumps(data, indent=2, ensure_ascii=False)
    json_str = json_str.replace("\n", "\r\n")
    path.write_text(json_str, encoding="utf-8", newline="")


def load_json(path: Path | str) -> dict[str, Any]:
    """Load a JSON file."""
    path = Path(path)
    return json.loads(path.read_bytes())
