"""Analyze managed .NET assemblies for type information.

Requires optional dependency: dnfile (pip install murder-unpack[binary])
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class FieldInfo:
    name: str
    type_name: str


@dataclass
class TypeInfo:
    namespace: str
    name: str
    base_type: str | None = None
    fields: list[FieldInfo] = field(default_factory=list)
    is_enum: bool = False
    is_struct: bool = False

    @property
    def full_name(self) -> str:
        if self.namespace:
            return f"{self.namespace}.{self.name}"
        return self.name


def analyze_assembly(path: Path | str, namespace_filter: str = "") -> list[TypeInfo]:
    """Analyze a managed .NET assembly for type definitions.

    Args:
        path: Path to the .dll assembly
        namespace_filter: Only return types in this namespace (empty = all)

    Returns:
        List of TypeInfo objects

    Raises:
        ImportError: If dnfile is not installed
    """
    try:
        import dnfile
    except ImportError:
        raise ImportError(
            "dnfile is required for assembly analysis. "
            "Install with: pip install murder-unpack[binary]"
        )

    path = Path(path)
    pe = dnfile.dnPE(str(path))

    if pe.net is None:
        return []

    types: list[TypeInfo] = []
    type_defs = pe.net.mdtables.TypeDef

    if type_defs is None:
        return []

    for row in type_defs:
        ns = row.TypeNamespace or ""
        name = row.TypeName or ""

        if namespace_filter and not ns.startswith(namespace_filter):
            continue

        # Determine base type
        base_type = None
        if hasattr(row, "Extends") and row.Extends:
            base_row = row.Extends.row
            if hasattr(base_row, "TypeName"):
                base_ns = getattr(base_row, "TypeNamespace", "") or ""
                base_name = base_row.TypeName or ""
                base_type = f"{base_ns}.{base_name}" if base_ns else base_name

        # Check flags for struct/enum
        flags = getattr(row, "Flags", 0) or 0
        is_struct = base_type in ("System.ValueType",)
        is_enum = base_type in ("System.Enum",)

        type_info = TypeInfo(
            namespace=ns,
            name=name,
            base_type=base_type,
            is_enum=is_enum,
            is_struct=is_struct,
        )

        # Extract fields
        field_list = getattr(row, "FieldList", None)
        if field_list:
            for field_row in field_list:
                fname = getattr(field_row, "Name", "") or ""
                # Field type requires signature parsing — simplified here
                type_info.fields.append(FieldInfo(name=fname, type_name="object"))

        types.append(type_info)

    return types
