"""Asset type registry mapping $type strings to editor directory paths.

Mirrors the EditorFolder/SaveLocation logic from Murder Engine's GameAsset subclasses.
FileHelper.Clean() strips non-[a-zA-Z0-9/\\_ -] characters.
"""

from __future__ import annotations

import re
from typing import Any

# Regex matching Murder's FileHelper.Clean() — [^a-zA-Z0-9/\\_ -] stripped
_CLEAN_RE = re.compile(r"[^a-zA-Z0-9/\\_ -]")


def clean_editor_folder(folder: str) -> str:
    """Mirror FileHelper.Clean() — strip icon chars and # prefix."""
    return _CLEAN_RE.sub("", folder).replace("\\", "/").strip("/")


# Mapping: $type → (base_path, editor_folder)
# base_path is "data" for GenericAssetsPath or "ecs" for ContentECSPath
# editor_folder is the cleaned EditorFolder value
_TYPE_MAP: dict[str, tuple[str, str]] = {
    # --- Murder Engine types ---
    "Murder.Assets.Graphics.SpriteAsset": ("data", "__from_editorPath__"),
    "Murder.Assets.WorldAsset": ("ecs", "World"),
    "Murder.Assets.PrefabAsset": ("ecs", "Prefabs"),
    "Murder.Assets.CharacterAsset": ("data", "Story/Characters"),
    "Murder.Assets.Graphics.FontAsset": ("data", "Fonts"),
    "Murder.Assets.FeatureAsset": ("data", "Features"),
    "Murder.Assets.Graphics.TilesetAsset": ("data", "Tilesets"),
    "Murder.Assets.Graphics.FloorAsset": ("data", "Tilesets/Floors"),
    "Murder.Assets.Graphics.ParticleSystemAsset": ("data", "Particles"),
    "Murder.Assets.Localization.LocalizationAsset": ("data", "Localization"),
    "Murder.Assets.SmartIntAsset": ("data", "Smart"),
    "Murder.Assets.SmartFloatAsset": ("data", "Smart"),
    "Murder.Assets.Sounds.SpeakerEventsAsset": ("data", "Sounds/Speakers"),
    "Murder.Assets.WorldEventsAsset": ("data", "Global Events"),
    "Murder.Assets.Graphics.TextIconsAsset": ("data", "Story"),
    "Murder.Assets.TextIconsAsset": ("data", "Story"),
    "Murder.Assets.Input.InputProfileAsset": ("data", ""),
    "Murder.Assets.Input.InputGraphicsAsset": ("data", "Ui"),
    "Murder.Assets.Dialogs.SpeakerAsset": ("data", "Story/Speakers"),
    "Murder.Assets.Editor.SpriteEventDataManagerAsset": ("data", "_Hidden"),
    "Murder.Assets.Editor.FilterLocalizationAsset": ("data", "_Hidden"),
    "Murder.Assets.InputGraphicsAsset": ("data", "Ui"),
    # GameProfile is special — stored at root
    "Murder.Assets.GameProfile": ("", ""),
}


def is_game_profile_type(type_name: str) -> bool:
    """Check if a type is a GameProfile (engine or game-specific subclass)."""
    return type_name == "Murder.Assets.GameProfile" or type_name.endswith("GameProfile")


def get_asset_directory(asset: dict[str, Any]) -> str:
    """Determine the editor directory path for an asset.

    Returns a path like "assets/data/Fonts" or "assets/ecs/World".
    """
    type_name = asset.get("$type", "")

    # GameProfile subclasses (game-specific) — stored at root
    if is_game_profile_type(type_name):
        return ""

    # Check known type mapping
    if type_name in _TYPE_MAP:
        base, folder = _TYPE_MAP[type_name]
        # SpriteAsset uses dynamic editorPath from JSON
        if folder == "__from_editorPath__":
            editor_path = asset.get("editorPath", "Generated")
            folder = clean_editor_folder(editor_path)
        if not base:
            return ""  # GameProfile — root level
        if folder:
            return f"assets/{base}/{folder}"
        return f"assets/{base}"

    # Unknown types default to data/
    return "assets/data"


def get_asset_filename(asset: dict[str, Any]) -> str:
    """Get the filename for an individual asset JSON file."""
    name = asset.get("Name", "")
    if not name:
        guid = asset.get("Guid", "unknown")
        name = f"unnamed_{guid}"
    # Sanitize filename
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    return f"{name}.json"


def get_save_location(type_name: str) -> str:
    """Get the SaveLocation base for a type (data/ or ecs/)."""
    if type_name in _TYPE_MAP:
        base, _ = _TYPE_MAP[type_name]
        return base
    return "data"
