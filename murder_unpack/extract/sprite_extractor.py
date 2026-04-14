"""Extract individual sprites from Murder Engine texture atlases."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from murder_unpack.core.gzip_json import load_json
from murder_unpack.core.qoi import decode_qoi_gz


class SpriteExtractor:
    """Extract sprites from atlas sheets using atlas JSON metadata."""

    def __init__(self, atlas_dir: Path | str) -> None:
        self.atlas_dir = Path(atlas_dir)
        self._texture_cache: dict[str, Image.Image] = {}

    def _load_texture(self, atlas_id: str, index: int) -> Image.Image:
        """Load an atlas texture sheet, with caching."""
        key = f"{atlas_id}{index:03d}"
        if key not in self._texture_cache:
            path = self.atlas_dir / f"{key}.qoi.gz"
            if not path.exists():
                raise FileNotFoundError(f"Atlas texture not found: {path}")
            self._texture_cache[key] = decode_qoi_gz(path)
        return self._texture_cache[key]

    def extract_sprite(
        self,
        entry: dict[str, Any],
        atlas_id: str,
        untrim: bool = True,
    ) -> Image.Image:
        """Extract a single sprite from an atlas.

        Args:
            entry: Atlas entry dict with SourceRectangle, TrimArea, Size, AtlasIndex
            atlas_id: Atlas identifier (e.g. "atlas", "preload")
            untrim: If True, reconstruct original image size with trim offset

        Returns:
            PIL Image of the extracted sprite
        """
        atlas_index = entry.get("AtlasIndex", 0)
        texture = self._load_texture(atlas_id, atlas_index)

        # Crop from atlas using SourceRectangle
        src = entry["SourceRectangle"]
        x, y, w, h = src["X"], src["Y"], src["Width"], src["Height"]
        cropped = texture.crop((x, y, x + w, y + h))

        if not untrim:
            return cropped

        # Reconstruct original size using TrimArea
        size = entry.get("Size", {})
        orig_w = size.get("X", w)
        orig_h = size.get("Y", h)

        trim = entry.get("TrimArea", {})
        trim_x = trim.get("X", 0)
        trim_y = trim.get("Y", 0)

        if orig_w == w and orig_h == h and trim_x == 0 and trim_y == 0:
            return cropped

        # Create transparent canvas of original size and paste trimmed content
        result = Image.new("RGBA", (orig_w, orig_h), (0, 0, 0, 0))
        result.paste(cropped, (trim_x, trim_y))
        return result

    def extract_all_from_atlas(
        self,
        atlas_name: str,
        output_dir: Path | str,
        untrim: bool = True,
    ) -> int:
        """Extract all sprites from an atlas to individual PNG files.

        Returns count of extracted sprites.
        """
        output_dir = Path(output_dir)
        metadata_path = self.atlas_dir / f"{atlas_name}.json"
        metadata = load_json(metadata_path)

        atlas_id = metadata.get("AtlasId", atlas_name)
        entries = metadata.get("entries", {})
        count = 0

        for name, entry in entries.items():
            sprite = self.extract_sprite(entry, atlas_id, untrim=untrim)

            # Convert backslash paths to proper path components for cross-platform
            parts = name.replace("\\", "/").split("/")
            parts[-1] = parts[-1] + ".png"
            out_path = output_dir.joinpath(*parts)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            sprite.save(out_path)
            count += 1

        return count

    def extract_animation_frames(
        self,
        sprite_asset: dict[str, Any],
        atlas_metadata: dict[str, Any],
    ) -> list[Image.Image]:
        """Extract all frames of a SpriteAsset animation.

        Args:
            sprite_asset: SpriteAsset dict with Frames array
            atlas_metadata: The atlas JSON metadata

        Returns:
            List of PIL Images, one per frame
        """
        atlas_id = atlas_metadata.get("AtlasId", "")
        frames_data = sprite_asset.get("Frames", [])
        images = []

        for frame in frames_data:
            img = self.extract_sprite(frame, atlas_id, untrim=True)
            images.append(img)

        return images
