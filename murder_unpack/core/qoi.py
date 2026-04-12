"""QOI image decode/encode for Murder Engine atlas textures and fonts."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import qoi
from PIL import Image

from murder_unpack.core.gzip_json import compress_bytes_gz, decompress_gz_bytes


def decode_qoi_gz(path: Path | str) -> Image.Image:
    """Decode a .qoi.gz file to a PIL Image.

    Murder stores atlas textures and font sheets as gzipped QOI.
    """
    raw = decompress_gz_bytes(path)
    arr = qoi.decode(raw)
    return Image.fromarray(arr)


def decode_qoi(data: bytes) -> Image.Image:
    """Decode raw QOI bytes to a PIL Image."""
    arr = qoi.decode(data)
    return Image.fromarray(arr)


def encode_to_qoi_gz(image: Image.Image, path: Path | str) -> None:
    """Encode a PIL Image to .qoi.gz format."""
    path = Path(path)
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    arr = np.array(image)
    qoi_bytes = qoi.encode(arr)
    compress_bytes_gz(qoi_bytes, path)


def encode_to_qoi(image: Image.Image) -> bytes:
    """Encode a PIL Image to raw QOI bytes."""
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    arr = np.array(image)
    return qoi.encode(arr)
