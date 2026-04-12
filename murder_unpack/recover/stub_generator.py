"""Auto-generate C# stub classes for game-specific types from JSON data.

Analyzes packed JSON assets to infer field names and types, then generates
compilable C# source files with [Serialize] attributes.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from murder_unpack.extract.game_data import GameDatabase

# GUID pattern: 8-4-4-4-12 hex
_GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

# Common base GameAsset fields to exclude from stubs
_BASE_ASSET_FIELDS = {"$type", "Name", "Guid"}


def infer_csharp_type(value: Any) -> str:
    """Infer a C# type from a JSON value."""
    if value is None:
        return "object?"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        if value == int(value) and abs(value) < 2**31:
            return "float"
        return "float"
    if isinstance(value, str):
        if _GUID_RE.match(value):
            return "Guid"
        return "string"
    if isinstance(value, list):
        if not value:
            return "ImmutableArray<object>"
        inner = infer_csharp_type(value[0])
        return f"ImmutableArray<{inner}>"
    if isinstance(value, dict):
        # Check if it looks like a Murder struct (X/Y, Width/Height, etc.)
        keys = set(value.keys())
        if keys == {"X", "Y"}:
            return "Point"
        if keys == {"X", "Y", "Width", "Height"}:
            return "IntRectangle"
        if keys == {"X", "Y", "Z", "W"}:
            return "Vector4"
        if keys == {"R", "G", "B", "A"}:
            return "Color"
        if keys == {"Data1", "Data2", "Data3", "Data4", "Path"}:
            return "FmodId"
        if "$type" in value:
            # Nested typed object — use the type name
            return _short_type_name(value["$type"])
        return "object"
    return "object"


def _short_type_name(full_type: str) -> str:
    """Convert full type name to short name."""
    return full_type.rsplit(".", 1)[-1]


def collect_type_schemas(db: GameDatabase) -> dict[str, dict[str, str]]:
    """Collect field schemas for all game-specific types from packed data.

    Returns: dict of type_name → dict of field_name → csharp_type
    """
    schemas: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

    for asset in db.all_assets():
        type_name = asset.get("$type", "")
        if not type_name:
            continue

        for key, value in asset.items():
            if key in _BASE_ASSET_FIELDS:
                continue
            csharp_type = infer_csharp_type(value)
            schemas[type_name][key].add(csharp_type)

    # Resolve multiple types for same field to most general
    result: dict[str, dict[str, str]] = {}
    for type_name, fields in schemas.items():
        result[type_name] = {}
        for field_name, types in fields.items():
            if len(types) == 1:
                result[type_name][field_name] = next(iter(types))
            elif "object" in types or "object?" in types:
                result[type_name][field_name] = "object"
            else:
                result[type_name][field_name] = "object"

    return result


def _get_base_class(type_name: str) -> str:
    """Determine the base class for a type."""
    if "GameProfile" in type_name:
        return "GameProfile"
    if "SaveData" in type_name:
        return "GameAsset"
    if "Speaker" in type_name and "Asset" in type_name:
        return "GameAsset"
    return "GameAsset"


def generate_stubs(
    db: GameDatabase,
    output_dir: Path | str,
    namespace_filter: str = "Road.",
) -> int:
    """Generate C# stub classes for game-specific types.

    Args:
        db: Loaded GameDatabase
        output_dir: Output directory for .cs files
        namespace_filter: Only generate stubs for types in this namespace

    Returns:
        Count of generated stub files
    """
    output_dir = Path(output_dir)
    schemas = collect_type_schemas(db)
    count = 0

    for type_name, fields in schemas.items():
        if namespace_filter and not type_name.startswith(namespace_filter):
            continue

        # Parse namespace and class name
        parts = type_name.rsplit(".", 1)
        if len(parts) == 2:
            namespace, class_name = parts
        else:
            namespace = "Road.Assets"
            class_name = parts[0]

        base_class = _get_base_class(type_name)

        # Build C# source
        lines = [
            "// Auto-generated stub from packed game data",
            "// Field types are inferred from JSON — review and adjust as needed",
            "",
            "using Bang;",
            "using Murder.Assets;",
            "using Murder.Core.Geometry;",
            "using System.Collections.Immutable;",
            "using System.Numerics;",
            "",
            f"namespace {namespace};",
            "",
            f"public class {class_name} : {base_class}",
            "{",
        ]

        for field_name, field_type in sorted(fields.items()):
            lines.append(f"    [Serialize]")
            lines.append(f"    public {field_type} {field_name} {{ get; set; }}")
            lines.append("")

        lines.append("}")
        lines.append("")

        # Write to namespace-based directory structure
        ns_path = namespace.replace(".", "/")
        file_dir = output_dir / ns_path
        file_dir.mkdir(parents=True, exist_ok=True)
        file_path = file_dir / f"{class_name}.cs"
        file_path.write_text("\n".join(lines), encoding="utf-8")
        count += 1

    return count
