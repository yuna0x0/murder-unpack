"""Extract type information from NativeAOT binaries by scanning for strings.

Works on any platform's binary (PE, ELF, Mach-O) — just scans raw bytes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ExtractedTypes:
    assets: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    systems: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    state_machines: list[str] = field(default_factory=list)
    interactions: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (len(self.assets) + len(self.components) + len(self.systems) +
                len(self.services) + len(self.state_machines) +
                len(self.interactions) + len(self.other))


_ENGINE_ROOTS = {
    b"Murder", b"Bang", b"Gum", b"System", b"Microsoft", b"MonoGame",
    b"FNA", b"Newtonsoft", b"Internal", b"Interop", b"Windows",
}


def _detect_namespace_from_binary(data: bytes) -> str:
    """Auto-detect game namespace from a NativeAOT binary.

    Scans for dotted identifiers like Foo.Bar.Baz and counts root namespaces,
    excluding known engine/framework roots.
    """
    pattern = re.compile(rb"([A-Z][a-zA-Z0-9]{1,30})\.[A-Z][a-zA-Z0-9_.]*(?:Asset|Component|System|Service|StateMachine|Interaction)")
    counts: dict[bytes, int] = {}
    for m in pattern.finditer(data):
        root = m.group(1)
        if root not in _ENGINE_ROOTS:
            counts[root] = counts.get(root, 0) + 1
    if counts:
        best = max(counts, key=counts.get)
        return best.decode("ascii") + "."
    return ""


def extract_type_names(
    path: Path | str,
    namespace_prefix: str = "",
) -> ExtractedTypes:
    """Extract .NET type names from a NativeAOT binary.

    NativeAOT binaries embed type name strings for reflection metadata,
    stack traces, and serialization. We scan for these patterns.

    Args:
        path: Path to the native binary (any platform)
        namespace_prefix: Namespace prefix to search for (auto-detected if empty)
    """
    data = Path(path).read_bytes()

    # Auto-detect game namespace if not specified
    if not namespace_prefix:
        namespace_prefix = _detect_namespace_from_binary(data)

    pattern = re.compile(
        namespace_prefix.encode("ascii").replace(b".", rb"\.") +
        rb"[A-Za-z_][A-Za-z0-9_.]*"
    )

    raw_matches: set[str] = set()
    for m in pattern.finditer(data):
        name = m.group().decode("ascii", errors="replace")
        if not name.endswith("."):
            raw_matches.add(name)

    result = ExtractedTypes()
    for name in sorted(raw_matches):
        if ".Assets." in name or name.endswith("Asset"):
            result.assets.append(name)
        elif ".Components." in name or name.endswith("Component"):
            result.components.append(name)
        elif ".Systems." in name or name.endswith("System"):
            result.systems.append(name)
        elif ".Services." in name or name.endswith("Service"):
            result.services.append(name)
        elif ".StateMachines." in name or name.endswith("StateMachine"):
            result.state_machines.append(name)
        elif ".Interactions." in name or name.endswith("Interaction"):
            result.interactions.append(name)
        else:
            result.other.append(name)

    return result
