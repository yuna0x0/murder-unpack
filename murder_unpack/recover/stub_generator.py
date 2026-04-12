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
            return "SoundEventId"
        if "$type" in value:
            # Nested typed object — only use Murder engine types that are
            # guaranteed to exist. Game-specific types and generics use object.
            type_name = value["$type"]
            if "<" in type_name:
                return "object"
            if not type_name.startswith("Murder."):
                return "object"
            return _short_type_name(type_name)
        return "object"
    return "object"


def _short_type_name(full_type: str) -> str:
    """Convert full C# type name to a safe short name.

    Handles generic types like:
      Bang.Interactions.InteractiveComponent<Road.Interactions.Foo>
      → InteractiveComponent_Foo
    """
    # Strip generic type arguments first, flatten to safe identifier
    if "<" in full_type:
        # Extract outer type and inner type(s)
        base, rest = full_type.split("<", 1)
        inner = rest.rstrip(">")
        base_short = base.rsplit(".", 1)[-1]
        inner_short = inner.rsplit(".", 1)[-1]
        return f"{base_short}_{inner_short}"
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
            "using Murder.Core.Sounds;",
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

    # Generate component stubs from world/prefab data
    comp_count = _generate_component_stubs(db, output_dir, namespace_filter)
    count += comp_count

    return count


def _scan_component_types(db: GameDatabase, namespace_filter: str) -> set[str]:
    """Scan all world/prefab assets for component $type references."""
    comp_types: set[str] = set()

    def scan(obj: Any, depth: int = 0) -> None:
        if depth > 15:
            return
        if isinstance(obj, dict):
            t = obj.get("$type", "")
            if t and namespace_filter and t.startswith(namespace_filter):
                if "Component" in t:
                    comp_types.add(t)
            for v in obj.values():
                scan(v, depth + 1)
        elif isinstance(obj, list):
            for v in obj:
                scan(v, depth + 1)

    for asset in db.all_assets():
        t = asset.get("$type", "")
        if "World" in t or "Prefab" in t:
            scan(asset)

    return comp_types


def _generate_component_stubs(
    db: GameDatabase,
    output_dir: Path,
    namespace_filter: str,
) -> int:
    """Generate empty IComponent struct stubs for game-specific components.

    This allows the Murder editor to load world entities without crashing
    on IndexOutOfRangeException — the ComponentsLookup will have entries
    for all component types even though they have no behavior.
    """
    comp_types = _scan_component_types(db, namespace_filter)
    count = 0

    for type_name in sorted(comp_types):
        parts = type_name.rsplit(".", 1)
        if len(parts) == 2:
            namespace, class_name = parts
        else:
            continue

        lines = [
            "// Auto-generated component stub for editor compatibility",
            "// This is an empty struct — original game logic is not recoverable",
            "",
            "using Bang.Components;",
            "",
            f"namespace {namespace};",
            "",
            f"public readonly struct {class_name} : IComponent",
            "{",
            "}",
            "",
        ]

        ns_path = namespace.replace(".", "/")
        file_dir = output_dir / ns_path
        file_dir.mkdir(parents=True, exist_ok=True)
        file_path = file_dir / f"{class_name}.cs"
        if not file_path.exists():  # Don't overwrite asset stubs
            file_path.write_text("\n".join(lines), encoding="utf-8")
            count += 1

    return count
